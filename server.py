"""Local comment-verification service for the Dropnote prototype.

Fetches public comments with the open-source youtube-comment-downloader project.
This is a best-effort web scraper, not a stable YouTube API. YouTube can change
its pages or restrict requests at any time. See README for production caveats.
"""
from __future__ import annotations

import os
import re
import hmac
import hashlib
import secrets
import sqlite3
import time
import json
import threading
from typing import Literal
from datetime import date
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_RECENT

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))

if USE_POSTGRES:
    try:
        import psycopg
        from psycopg_pool import ConnectionPool
        from psycopg.errors import IntegrityError as PgIntegrityError

        class RowWrapper(dict):
            def __getitem__(self, item):
                if isinstance(item, int):
                    return list(self.values())[item]
                return super().__getitem__(item)

        def make_row(cursor):
            if not cursor.description:
                return lambda values: values
            fields = [c.name for c in cursor.description]
            def row_factory(values):
                return RowWrapper(zip(fields, values))
            return row_factory

        pg_pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=10,
            max_idle=300.0,
            check=ConnectionPool.check_connection,
            kwargs={"row_factory": make_row},
        )

        class PgConnectionWrapper:
            def __init__(self, conn, pool):
                self._conn = conn
                self._pool = pool
                self._closed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is not None:
                    self.rollback()
                self.close()

            def execute(self, sql: str, params=None):
                clean_sql = sql.strip().upper()
                if clean_sql.startswith("BEGIN"):
                    return self
                target_sql = sql.replace("?", "%s") if params is not None else sql
                try:
                    if params is not None:
                        return self._conn.execute(target_sql, params)
                    return self._conn.execute(target_sql)
                except Exception as e:
                    if "closed the connection" in str(e).lower() or getattr(self._conn, "broken", False) or getattr(self._conn, "closed", False):
                        try:
                            self._conn = self._pool.getconn()
                            if params is not None:
                                return self._conn.execute(target_sql, params)
                            return self._conn.execute(target_sql)
                        except Exception:
                            raise e
                    raise

            def commit(self):
                try:
                    self._conn.commit()
                except Exception:
                    pass

            def rollback(self):
                try:
                    self._conn.rollback()
                except Exception:
                    pass

            def close(self):
                if not self._closed:
                    try:
                        if not self._conn.closed and not getattr(self._conn, "broken", False):
                            self._conn.rollback()
                    except Exception:
                        pass
                    try:
                        self._pool.putconn(self._conn)
                    except Exception:
                        pass
                    self._closed = True

        IntegrityErrors = (sqlite3.IntegrityError, PgIntegrityError)
    except Exception as _e:
        USE_POSTGRES = False
        IntegrityErrors = (sqlite3.IntegrityError,)
else:
    IntegrityErrors = (sqlite3.IntegrityError,)

DEFAULT_DB_PATH = Path(os.environ.get("DROPNOTE_DB", "dropnote.sqlite3"))
DB_PATH = DEFAULT_DB_PATH
MAX_SCAN_COMMENTS = int(os.environ.get("MAX_SCAN_COMMENTS", "250"))
COMMENT_CACHE_TTL = float(os.environ.get("COMMENT_CACHE_TTL", "15"))
COMMENT_CACHE_MAX_VIDEOS = int(os.environ.get("COMMENT_CACHE_MAX_VIDEOS", "64"))
VIDEO_INFO_CACHE_TTL = float(os.environ.get("VIDEO_INFO_CACHE_TTL", "600"))
DB_TIMEOUT_SECONDS = 5.0
CODE_RE = re.compile(r"^[a-z]{1,24}(?:[- ]+[a-z]{1,24}){2,}\.?$", re.IGNORECASE)

app = FastAPI(title="Dropnote verification service", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
DIST_PATH = Path(__file__).parent / "dist"
if (DIST_PATH / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_PATH / "assets"), name="assets")


@app.middleware("http")
async def cache_policy(request: Request, call_next):
    """Hashed build assets can be cached forever; API responses never can."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.api_route("/", methods=["GET", "HEAD"])
def frontend():
    index = DIST_PATH / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Frontend build is missing. Run npm run build first.")
    return FileResponse(index)


def db():
    if USE_POSTGRES and DB_PATH == DEFAULT_DB_PATH:
        conn = pg_pool.getconn()
        return PgConnectionWrapper(conn, pg_pool)
    connection = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def init_db():
    if USE_POSTGRES and DB_PATH == DEFAULT_DB_PATH:
        with closing(db()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    id SERIAL PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    author_channel_id TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(video_id, author_channel_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    handle TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'New resource',
                    accent TEXT NOT NULL DEFAULT '#6558E8',
                    claimed INTEGER NOT NULL DEFAULT 0,
                    max_claims INTEGER,
                    ends_at TEXT NOT NULL DEFAULT 'No end date',
                    status TEXT NOT NULL DEFAULT 'Live',
                    description TEXT NOT NULL DEFAULT 'A creator resource campaign.',
                    resource_url TEXT NOT NULL,
                    resource_type TEXT NOT NULL DEFAULT 'link',
                    resource_text TEXT NOT NULL DEFAULT '',
                    video_url TEXT NOT NULL,
                    initials TEXT NOT NULL,
                    creator_email TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS creators (
                    email TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    invite_approved INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS creator_invites (
                    invite_id TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL UNIQUE,
                    invited_email TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    used_at DOUBLE PRECISION,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("UPDATE campaigns SET claimed = (SELECT COUNT(*) FROM claims WHERE claims.campaign_id = campaigns.campaign_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_campaign ON claims(campaign_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_creator ON campaigns(creator_email)")
            conn.commit()
        return

    with closing(db()) as conn:
        # WAL keeps reads (campaign pages, downloads) available while a claim is written.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                author_channel_id TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(video_id, author_channel_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                campaign_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                channel TEXT NOT NULL,
                handle TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'New resource',
                accent TEXT NOT NULL DEFAULT '#6558E8',
                claimed INTEGER NOT NULL DEFAULT 0,
                max_claims INTEGER,
                ends_at TEXT NOT NULL DEFAULT 'No end date',
                status TEXT NOT NULL DEFAULT 'Live',
                description TEXT NOT NULL DEFAULT 'A creator resource campaign.',
                resource_url TEXT NOT NULL,
                resource_type TEXT NOT NULL DEFAULT 'link',
                resource_text TEXT NOT NULL DEFAULT '',
                video_url TEXT NOT NULL,
                initials TEXT NOT NULL,
                creator_email TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS creators (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                invite_approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS creator_invites (
                invite_id TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL UNIQUE,
                invited_email TEXT NOT NULL,
                created_by TEXT NOT NULL,
                expires_at REAL NOT NULL,
                used_at REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        claim_columns = {row[1] for row in conn.execute("PRAGMA table_info(claims)")}
        if "email" in claim_columns:
            # Remove any recovery email collected by an older prototype version.
            conn.execute("UPDATE claims SET email = NULL")
        # Keep counters derived from verified claim records, never client input.
        conn.execute("UPDATE campaigns SET claimed = (SELECT COUNT(*) FROM claims WHERE claims.campaign_id = campaigns.campaign_id)")
        campaign_columns = {row[1] for row in conn.execute("PRAGMA table_info(campaigns)")}
        if "creator_email" not in campaign_columns:
            conn.execute("ALTER TABLE campaigns ADD COLUMN creator_email TEXT")
        if "resource_type" not in campaign_columns:
            conn.execute("ALTER TABLE campaigns ADD COLUMN resource_type TEXT NOT NULL DEFAULT 'link'")
        if "resource_text" not in campaign_columns:
            conn.execute("ALTER TABLE campaigns ADD COLUMN resource_text TEXT NOT NULL DEFAULT ''")
        # File resources were removed; park legacy file campaigns until an owner edits them.
        conn.execute("UPDATE campaigns SET resource_type = 'link', status = 'Paused' WHERE resource_type NOT IN ('link', 'text')")
        creator_columns = {row[1] for row in conn.execute("PRAGMA table_info(creators)")}
        if "invite_approved" not in creator_columns:
            # Existing prototype accounts were created via open signup; require admin re-approval.
            conn.execute("ALTER TABLE creators ADD COLUMN invite_approved INTEGER NOT NULL DEFAULT 0")
        # Cover the lookups used by studio listings and claim counters.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_campaign ON claims(campaign_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_creator ON campaigns(creator_email)")
        conn.commit()


def extract_video_id(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    host = parsed.netloc.lower().split(":")[0]
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            video_id = parts[1] if len(parts) > 1 and parts[0] in {"shorts", "embed", "live"} else ""
    else:
        raise HTTPException(400, "Enter a valid YouTube video or Shorts URL.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise HTTPException(400, "Could not read a valid YouTube video ID from that link.")
    return video_id


# --- Short-lived caches -------------------------------------------------------
# Comment scraping is network bound and slow (seconds), so each video is scraped
# at most once per COMMENT_CACHE_TTL window and concurrent checks share the work.
_comment_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_comment_locks: dict[str, threading.Lock] = {}
_cache_lock = threading.Lock()
_video_info_cache: dict[str, tuple[float, dict[str, str]]] = {}


def _fresh_comments(video_id: str) -> list[dict[str, str]] | None:
    entry = _comment_cache.get(video_id)
    if entry and time.monotonic() - entry[0] < COMMENT_CACHE_TTL:
        return entry[1]
    return None


def _video_lock(video_id: str) -> threading.Lock:
    with _cache_lock:
        lock = _comment_locks.get(video_id)
        if lock is None:
            lock = _comment_locks[video_id] = threading.Lock()
        return lock


def _store_comments(video_id: str, comments: list[dict[str, str]]) -> None:
    with _cache_lock:
        _comment_cache[video_id] = (time.monotonic(), comments)
        overflow = len(_comment_cache) - COMMENT_CACHE_MAX_VIDEOS
        if overflow > 0:
            oldest = sorted(_comment_cache.items(), key=lambda item: item[1][0])[:overflow]
            for stale_id, _ in oldest:
                _comment_cache.pop(stale_id, None)
                lock = _comment_locks.get(stale_id)
                if lock is None or not lock.locked():
                    _comment_locks.pop(stale_id, None)


def recent_comments(video_id: str) -> list[dict[str, str]]:
    """Newest comments for a video, coalescing parallel requests into one scrape."""
    comments = _fresh_comments(video_id)
    if comments is not None:
        return comments
    with _video_lock(video_id):
        comments = _fresh_comments(video_id)
        if comments is not None:
            return comments
        scraped: list[dict[str, str]] = []
        for comment in YoutubeCommentDownloader().get_comments(video_id, SORT_BY_RECENT):
            scraped.append({
                "text": comment.get("text") or "",
                "channel": (comment.get("channel") or "").strip(),
                "cid": (comment.get("cid") or "").strip(),
            })
            if len(scraped) >= MAX_SCAN_COMMENTS:
                break
        _store_comments(video_id, scraped)
        return scraped


def cached_video_info(video_id: str) -> dict[str, str] | None:
    entry = _video_info_cache.get(video_id)
    if entry and time.monotonic() - entry[0] < VIDEO_INFO_CACHE_TTL:
        return entry[1]
    return None


def store_video_info(video_id: str, info: dict[str, str]) -> dict[str, str]:
    with _cache_lock:
        _video_info_cache[video_id] = (time.monotonic(), info)
        if len(_video_info_cache) > 256:
            oldest = sorted(_video_info_cache.items(), key=lambda item: item[1][0])[: len(_video_info_cache) - 256]
            for stale_id, _ in oldest:
                _video_info_cache.pop(stale_id, None)
    return info


class VerifyRequest(BaseModel):
    campaignId: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=8, max_length=60)

    class Config:
        extra = "forbid"


class AuthPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class SignupPayload(AuthPayload):
    inviteCode: str = Field(min_length=20, max_length=120)


class InviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class VideoInfoRequest(BaseModel):
    video: str = Field(min_length=10, max_length=500)


class CampaignStatusUpdate(BaseModel):
    status: Literal["Live", "Paused"]


class CampaignUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    channel: str = Field(min_length=1, max_length=120)
    handle: str = Field(default='', max_length=100)
    category: str = Field(default='New resource', max_length=80)
    accent: str = Field(default='#777B77', max_length=20)
    limit: int | None = Field(default=None, ge=1)
    ends: str = Field(default='No end date', max_length=40)
    status: Literal["Live", "Paused"] = "Live"
    description: str = Field(default='A new creator resource campaign.', max_length=500)
    resourceType: Literal["link", "text"] = "link"
    resource: str = Field(min_length=1, max_length=5000)
    video: str = Field(min_length=10, max_length=500)
    initials: str = Field(default='CR', max_length=4)


class CampaignCreate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=160)
    channel: str = Field(min_length=1, max_length=120)
    handle: str = Field(default='', max_length=100)
    category: str = Field(default='New resource', max_length=80)
    accent: str = Field(default='#6558E8', max_length=20)
    limit: int | None = Field(default=None, ge=1)
    ends: str = Field(default='No end date', max_length=40)
    status: Literal["Live", "Paused"] = "Live"
    description: str = Field(default='A new creator resource campaign.', max_length=500)
    resourceType: Literal["link", "text"] = "link"
    resource: str = Field(min_length=1, max_length=5000)
    video: str = Field(min_length=10, max_length=500)
    initials: str = Field(default='CR', max_length=4)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "database": "neon_postgres" if USE_POSTGRES else "sqlite",
        "verification": "youtube-comment-downloader",
    }


SESSION_SECONDS = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 310_000
SESSION_COOKIE = "dropnote_session"


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise HTTPException(422, "Enter a valid email address.")
    return normalized


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def cookie_is_secure(request: Request) -> bool:
    configured = os.getenv("DROPNOTE_COOKIE_SECURE", "").strip().lower()
    if configured in {"true", "1", "yes"}:
        return True
    if configured in {"false", "0", "no"}:
        return False
    return request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip() == "https"


def set_login_cookie(response: Response, request: Request, email: str, role: str):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with closing(db()) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        conn.execute("INSERT INTO sessions(token_hash,email,role,expires_at) VALUES(?,?,?,?)", (token_hash, email, role, time.time() + SESSION_SECONDS))
        conn.commit()
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=cookie_is_secure(request), samesite="lax", path="/")


def get_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with closing(db()) as conn:
        row = conn.execute("SELECT email,role,expires_at FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return None
    if row["role"] == "admin" and row["email"] != os.getenv("DROPNOTE_ADMIN_EMAIL", "").strip().lower():
        return None
    if row["role"] == "creator":
        with closing(db()) as conn:
            approved = conn.execute("SELECT invite_approved FROM creators WHERE email = ?", (row["email"],)).fetchone()
        if not approved or not approved["invite_approved"]:
            return None
    return {"email": row["email"], "role": row["role"]}


def require_user(user=Depends(get_current_user)):
    if not user:
        raise HTTPException(401, "Sign in to your Studio account to continue.")
    return user


@app.get("/api/auth/me")
def auth_me(user=Depends(get_current_user)):
    return {"authenticated": bool(user), "user": user}


@app.post("/api/auth/signup")
def auth_signup(payload: SignupPayload, request: Request, response: Response):
    email = normalize_email(payload.email)
    admin_email = os.getenv("DROPNOTE_ADMIN_EMAIL", "").strip().lower()
    if admin_email and hmac.compare_digest(email, admin_email):
        raise HTTPException(409, "This email is reserved for the environment-configured admin account.")
    invite_hash = hashlib.sha256(payload.inviteCode.encode()).hexdigest()
    password_hash = hash_password(payload.password)
    now = time.time()
    with closing(db()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            invite = conn.execute("SELECT invite_id,invited_email,expires_at,used_at FROM creator_invites WHERE code_hash = ?", (invite_hash,)).fetchone()
            if not invite or invite["used_at"] is not None or invite["expires_at"] < now:
                conn.rollback()
                raise HTTPException(403, "This creator invitation is invalid, expired, or already used.")
            if not hmac.compare_digest(invite["invited_email"], email):
                conn.rollback()
                raise HTTPException(403, "This invitation was issued to a different email address.")
            account = conn.execute("SELECT invite_approved FROM creators WHERE email = ?", (email,)).fetchone()
            if account and account["invite_approved"]:
                conn.rollback()
                raise HTTPException(409, "An approved account with this email already exists. Sign in instead.")
            conn.execute("""INSERT INTO creators(email,password_hash,invite_approved) VALUES(?,?,1)
                ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash, invite_approved=1
                WHERE creators.invite_approved=0""", (email, password_hash))
            updated = conn.execute("UPDATE creator_invites SET used_at = ? WHERE invited_email = ? AND used_at IS NULL AND expires_at >= ?", (now, email, now)).rowcount
            if updated < 1:
                conn.rollback()
                raise HTTPException(403, "This invitation has already been used or expired.")
            conn.execute("DELETE FROM sessions WHERE email = ? AND role = 'creator'", (email,))
            conn.commit()
        except IntegrityErrors as exc:
            conn.rollback()
            raise HTTPException(409, "An account with this email already exists. Sign in instead.") from exc
    set_login_cookie(response, request, email, "creator")
    return {"authenticated": True, "user": {"email": email, "role": "creator"}}


def require_admin(user=Depends(require_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


@app.post("/api/admin/invites")
def create_creator_invite(payload: InviteCreate, user=Depends(require_admin)):
    email = normalize_email(payload.email)
    admin_email = os.getenv("DROPNOTE_ADMIN_EMAIL", "").strip().lower()
    if email == admin_email:
        raise HTTPException(409, "Admin email already has administrator access.")
    token = secrets.token_urlsafe(32)
    invite_id = secrets.token_urlsafe(12)
    expires_at = time.time() + 7 * 24 * 60 * 60
    with closing(db()) as conn:
        exists = conn.execute("SELECT 1 FROM creators WHERE email = ? AND invite_approved = 1", (email,)).fetchone()
        if exists:
            raise HTTPException(409, "This email already has an approved creator account.")
        conn.execute("DELETE FROM creator_invites WHERE invited_email = ? AND used_at IS NULL", (email,))
        conn.execute("INSERT INTO creator_invites(invite_id,code_hash,invited_email,created_by,expires_at) VALUES(?,?,?,?,?)", (invite_id, hashlib.sha256(token.encode()).hexdigest(), email, user["email"], expires_at))
        conn.commit()
    return {"inviteCode": token, "email": email, "expiresAt": expires_at}


@app.get("/api/admin/invites")
def list_creator_invites(user=Depends(require_admin)):
    now = time.time()
    with closing(db()) as conn:
        rows = conn.execute("SELECT invite_id,invited_email,expires_at,used_at,created_at FROM creator_invites WHERE used_at IS NULL AND expires_at >= ? ORDER BY created_at DESC", (now,)).fetchall()
    return [dict(row) for row in rows]


@app.delete("/api/admin/invites/{invite_id}")
def revoke_creator_invite(invite_id: str, user=Depends(require_admin)):
    with closing(db()) as conn:
        result = conn.execute("DELETE FROM creator_invites WHERE invite_id = ? AND used_at IS NULL", (invite_id,))
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Active invitation not found.")
    return {"ok": True}


@app.post("/api/auth/login")
def auth_login(payload: AuthPayload, request: Request, response: Response):
    email = normalize_email(payload.email)
    admin_email = os.getenv("DROPNOTE_ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("DROPNOTE_ADMIN_PASSWORD", "")
    if admin_email and email == admin_email:
        if not admin_password or not hmac.compare_digest(payload.password, admin_password):
            raise HTTPException(401, "Email or password is incorrect.")
        role = "admin"
    else:
        with closing(db()) as conn:
            account = conn.execute("SELECT password_hash,invite_approved FROM creators WHERE email = ?", (email,)).fetchone()
        if not account or not account["invite_approved"] or not verify_password(payload.password, account["password_hash"]):
            raise HTTPException(401, "Email or password is incorrect.")
        role = "creator"
    set_login_cookie(response, request, email, role)
    return {"authenticated": True, "user": {"email": email, "role": role}}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with closing(db()) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            conn.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=cookie_is_secure(request), samesite="lax")
    return {"ok": True}


@app.get("/api/campaigns")
def list_campaigns():
    # Never expose resource_url in the public campaign list; return it only after verification.
    with closing(db()) as conn:
        rows = conn.execute("SELECT campaign_id,title,channel,handle,category,accent,claimed,max_claims,ends_at,status,description,video_url,initials,created_at FROM campaigns ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/studio/campaigns")
def studio_campaigns(user=Depends(require_user)):
    with closing(db()) as conn:
        if user["role"] == "admin":
            rows = conn.execute("SELECT campaign_id,title,channel,handle,category,accent,claimed,max_claims,ends_at,status,description,video_url,initials,resource_url,resource_type,resource_text,created_at FROM campaigns ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT campaign_id,title,channel,handle,category,accent,claimed,max_claims,ends_at,status,description,video_url,initials,resource_url,resource_type,resource_text,created_at FROM campaigns WHERE creator_email = ? ORDER BY created_at DESC", (user["email"],)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/youtube/info")
def youtube_video_info(payload: VideoInfoRequest, user=Depends(require_user)):
    video_id = extract_video_id(payload.video)
    cached = cached_video_info(video_id)
    if cached is not None:
        return cached
    oembed_url = f"https://www.youtube.com/oembed?url={quote(f'https://www.youtube.com/watch?v={video_id}', safe='')}&format=json"
    try:
        response = requests.get(oembed_url, headers={"User-Agent": "Dropnote/1.0 (+video metadata preview)"}, timeout=15)
        if response.status_code in (400, 401, 403, 404):
            raise HTTPException(422, "YouTube could not find public video details for that link.")
        response.raise_for_status()
        info = response.json()
    except HTTPException:
        raise
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, "Could not fetch YouTube details right now. Check the video link and try again.") from exc
    author_url = info.get("author_url", "")
    handle = urlparse(author_url).path.rsplit("/", 1)[-1] if author_url else ""
    return store_video_info(video_id, {
        "videoId": video_id,
        "title": info.get("title", ""),
        "channel": info.get("author_name", ""),
        "channelUrl": author_url,
        "handle": handle if handle.startswith("@") else "",
        "thumbnailUrl": info.get("thumbnail_url", ""),
    })


@app.post("/api/campaigns")
def create_campaign(payload: CampaignCreate, user=Depends(require_user)):
    extract_video_id(payload.video)
    if payload.resourceType == "link" and not payload.resource.startswith(("https://", "http://")):
        raise HTTPException(400, "Enter a valid resource URL.")
    with closing(db()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT INTO campaigns(campaign_id,title,channel,handle,category,accent,claimed,max_claims,ends_at,status,description,resource_url,resource_type,resource_text,video_url,initials,creator_email)
                VALUES(?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)
            """, (payload.id,payload.title,payload.channel,payload.handle,payload.category,payload.accent,payload.limit,payload.ends,payload.status,payload.description,payload.resource if payload.resourceType == "link" else "",payload.resourceType,payload.resource if payload.resourceType == "text" else "",payload.video,payload.initials,user["email"]))
            conn.commit()
        except IntegrityErrors as exc:
            conn.rollback()
            raise HTTPException(409, "That campaign ID already exists.") from exc
    return {"ok": True, "campaignId": payload.id}


@app.put("/api/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, payload: CampaignUpdate, user=Depends(require_user)):
    extract_video_id(payload.video)
    if payload.resourceType == "link" and not payload.resource.startswith(("https://", "http://")):
        raise HTTPException(400, "Enter a valid resource URL.")
    with closing(db()) as conn:
        existing = conn.execute("SELECT creator_email,claimed FROM campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Campaign not found.")
        if user["role"] != "admin" and existing["creator_email"] != user["email"]:
            raise HTTPException(403, "You do not have access to this campaign.")
        if payload.limit is not None and payload.limit < existing["claimed"]:
            raise HTTPException(409, "Claim limit cannot be lower than the number already claimed.")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            UPDATE campaigns SET title=?,channel=?,handle=?,category=?,accent=?,max_claims=?,ends_at=?,status=?,description=?,
                resource_url=?,resource_type=?,resource_text=?,video_url=?,initials=? WHERE campaign_id=?
        """, (payload.title,payload.channel,payload.handle,payload.category,payload.accent,payload.limit,payload.ends,payload.status,payload.description,
              payload.resource if payload.resourceType == "link" else "",payload.resourceType,payload.resource if payload.resourceType == "text" else "",payload.video,payload.initials,campaign_id))
        conn.commit()
    return {"ok": True, "campaignId": campaign_id}


@app.patch("/api/campaigns/{campaign_id}/status")
def update_campaign_status(campaign_id: str, payload: CampaignStatusUpdate, user=Depends(require_user)):
    with closing(db()) as conn:
        campaign = conn.execute("SELECT creator_email FROM campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not campaign:
            raise HTTPException(404, "Campaign not found.")
        if user["role"] != "admin" and campaign["creator_email"] != user["email"]:
            raise HTTPException(403, "You do not have access to this campaign.")
        conn.execute("UPDATE campaigns SET status = ? WHERE campaign_id = ?", (payload.status, campaign_id))
        conn.commit()
    return {"ok": True, "campaignId": campaign_id, "status": payload.status}


@app.delete("/api/campaigns/{campaign_id}")
def delete_campaign(campaign_id: str, user=Depends(require_user)):
    with closing(db()) as conn:
        campaign = conn.execute("SELECT creator_email FROM campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not campaign:
            raise HTTPException(404, "Campaign not found.")
        if user["role"] != "admin" and campaign["creator_email"] != user["email"]:
            raise HTTPException(403, "You do not have access to this campaign.")
        conn.execute("DELETE FROM claims WHERE campaign_id = ?", (campaign_id,))
        conn.execute("DELETE FROM campaigns WHERE campaign_id = ?", (campaign_id,))
        conn.commit()
    return {"ok": True, "campaignId": campaign_id}


class BatchStatusPayload(BaseModel):
    campaign_ids: list[str] = Field(default_factory=list)
    status: str = Field(pattern=r"^(Live|Paused)$")


class BatchDeletePayload(BaseModel):
    campaign_ids: list[str] = Field(min_length=1)


@app.post("/api/studio/campaigns/batch-status")
def batch_update_campaign_status(payload: BatchStatusPayload, user=Depends(require_user)):
    with closing(db()) as conn:
        if not payload.campaign_ids:
            if user["role"] == "admin":
                conn.execute("UPDATE campaigns SET status = ?", (payload.status,))
            else:
                conn.execute("UPDATE campaigns SET status = ? WHERE creator_email = ?", (payload.status, user["email"]))
        else:
            placeholders = ",".join("?" for _ in payload.campaign_ids)
            if user["role"] == "admin":
                conn.execute(f"UPDATE campaigns SET status = ? WHERE campaign_id IN ({placeholders})", (payload.status, *payload.campaign_ids))
            else:
                conn.execute(f"UPDATE campaigns SET status = ? WHERE creator_email = ? AND campaign_id IN ({placeholders})", (payload.status, user["email"], *payload.campaign_ids))
        conn.commit()
    return {"ok": True, "status": payload.status}


@app.post("/api/studio/campaigns/batch-delete")
def batch_delete_campaigns(payload: BatchDeletePayload, user=Depends(require_user)):
    with closing(db()) as conn:
        placeholders = ",".join("?" for _ in payload.campaign_ids)
        if user["role"] == "admin":
            conn.execute(f"DELETE FROM claims WHERE campaign_id IN ({placeholders})", (*payload.campaign_ids,))
            conn.execute(f"DELETE FROM campaigns WHERE campaign_id IN ({placeholders})", (*payload.campaign_ids,))
        else:
            owned_rows = conn.execute(f"SELECT campaign_id FROM campaigns WHERE creator_email = ? AND campaign_id IN ({placeholders})", (user["email"], *payload.campaign_ids)).fetchall()
            owned_ids = [r["campaign_id"] for r in owned_rows]
            if owned_ids:
                owned_placeholders = ",".join("?" for _ in owned_ids)
                conn.execute(f"DELETE FROM claims WHERE campaign_id IN ({owned_placeholders})", (*owned_ids,))
                conn.execute(f"DELETE FROM campaigns WHERE campaign_id IN ({owned_placeholders})", (*owned_ids,))
        conn.commit()
    return {"ok": True, "deleted": len(payload.campaign_ids)}


@app.post("/api/verify")
def verify_comment(payload: VerifyRequest):
    normalized_code = payload.code.strip().casefold()
    if not CODE_RE.fullmatch(normalized_code):
        raise HTTPException(400, "Invalid claim sentence. Use at least three words separated by spaces or hyphens.")
    with closing(db()) as conn:
        campaign = conn.execute("SELECT * FROM campaigns WHERE campaign_id = ?", (payload.campaignId,)).fetchone()
    if not campaign:
        raise HTTPException(404, "Campaign not found in the shared demo database. Create it in Studio first.")
    if campaign["status"] != "Live":
        raise HTTPException(410, "This campaign is no longer active.")
    if campaign["ends_at"] != "No end date":
        try:
            if date.fromisoformat(campaign["ends_at"]) < date.today():
                raise HTTPException(410, "This campaign has ended.")
        except ValueError as exc:
            raise HTTPException(500, "Campaign end date is invalid.") from exc
    video_id = extract_video_id(campaign["video_url"])

    try:
        comments = recent_comments(video_id)
    except Exception as exc:
        raise HTTPException(502, f"Could not check comments right now: {str(exc)[:180]}") from exc

    match = None
    for comment in comments:
        if normalized_code in comment["text"].casefold():
            match = comment
            break

    if not match:
        raise HTTPException(404, f"No matching comment found in the latest {len(comments)} comments. Make sure it is public and try again.")
    author_channel = (match.get("channel") or "").strip()
    comment_id = (match.get("cid") or "").strip()
    if not author_channel or not comment_id:
        raise HTTPException(502, "The comment was found, but its public channel identifier was unavailable.")

    try:
        with closing(db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute("SELECT claimed, max_claims, status, ends_at, resource_type FROM campaigns WHERE campaign_id = ?", (payload.campaignId,)).fetchone()
            if not latest:
                raise HTTPException(404, "Campaign not found.")
            if latest["status"] != "Live":
                raise HTTPException(410, "This campaign is no longer active.")
            if latest["ends_at"] != "No end date":
                try:
                    if date.fromisoformat(latest["ends_at"]) < date.today():
                        raise HTTPException(410, "This campaign has ended.")
                except ValueError as exc:
                    raise HTTPException(500, "Campaign end date is invalid.") from exc
            if latest["resource_type"] != campaign["resource_type"]:
                raise HTTPException(409, "The campaign resource changed while this claim was being checked. Please try again.")
            existing = conn.execute(
                "SELECT campaign_id FROM claims WHERE video_id = ? AND author_channel_id = ?",
                (video_id, author_channel),
            ).fetchone()
            if existing:
                if existing["campaign_id"] != payload.campaignId:
                    raise HTTPException(409, "This YouTube account has already claimed a drop for this video.")
                already_claimed = True
            else:
                if latest["max_claims"] and latest["claimed"] >= latest["max_claims"]:
                    raise HTTPException(410, "This campaign has reached its claim limit.")
                conn.execute(
                    "INSERT INTO claims(campaign_id, video_id, author_channel_id, comment_id) VALUES (?, ?, ?, ?)",
                    (payload.campaignId, video_id, author_channel, comment_id),
                )
                conn.execute("UPDATE campaigns SET claimed = claimed + 1 WHERE campaign_id = ?", (payload.campaignId,))
                already_claimed = False
            conn.commit()
    except IntegrityErrors as exc:
        raise HTTPException(409, "This YouTube account has already claimed a drop for this video.") from exc

    return {
        "verified": True,
        "alreadyClaimed": already_claimed,
        "campaignId": payload.campaignId,
        "videoId": video_id,
        "commentId": comment_id,
        "resourceType": campaign["resource_type"],
        "resourceUrl": campaign["resource_url"] if campaign["resource_type"] == "link" else None,
        "resourceText": campaign["resource_text"] if campaign["resource_type"] == "text" else None,
        "message": "Comment code matched. Claim recorded for this YouTube channel on this video.",
    }


@app.get("/api/claims/{campaign_id}")
def campaign_claims(campaign_id: str, user=Depends(require_user)):
    with closing(db()) as conn:
        campaign = conn.execute("SELECT creator_email FROM campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not campaign:
            raise HTTPException(404, "Campaign not found.")
        if user["role"] != "admin" and campaign["creator_email"] != user["email"]:
            raise HTTPException(403, "You do not have access to this campaign.")
        count = conn.execute("SELECT COUNT(*) AS n FROM claims WHERE campaign_id = ?", (campaign_id,)).fetchone()["n"]
    return {"campaignId": campaign_id, "verifiedClaims": count}


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    index = DIST_PATH / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Frontend build is missing. Run npm run build first.")
    return FileResponse(index)
