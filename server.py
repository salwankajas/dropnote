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
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException, Depends, Request, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_RECENT

DB_PATH = Path(os.environ.get("DROPNOTE_DB", "dropnote.sqlite3"))
UPLOAD_DIR = Path(os.environ.get("DROPNOTE_UPLOAD_DIR", str(DB_PATH.parent / "dropnote-uploads")))
MAX_RESOURCE_BYTES = 15 * 1024 * 1024
RESOURCE_TOKEN_SECONDS = 7 * 24 * 60 * 60
ALLOWED_RESOURCE_TYPES = {
    ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".zip": "application/zip",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}
MAX_SCAN_COMMENTS = int(os.environ.get("MAX_SCAN_COMMENTS", "250"))
COMMENT_CACHE_TTL = float(os.environ.get("COMMENT_CACHE_TTL", "15"))
COMMENT_CACHE_MAX_VIDEOS = int(os.environ.get("COMMENT_CACHE_MAX_VIDEOS", "64"))
VIDEO_INFO_CACHE_TTL = float(os.environ.get("VIDEO_INFO_CACHE_TTL", "600"))
DB_TIMEOUT_SECONDS = 5.0
CODE_RE = re.compile(r"^[a-z]{2,10}(?:[- ]+[a-z]{2,10}){2,}\.?$", re.IGNORECASE)

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


@app.get("/")
def frontend():
    index = DIST_PATH / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Frontend build is missing. Run npm run build first.")
    return FileResponse(index)


def db():
    connection = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def init_db():
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
                download_token_hash TEXT,
                download_token_expires_at REAL,
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
                resource_file_id TEXT,
                video_url TEXT NOT NULL,
                initials TEXT NOT NULL,
                creator_email TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resource_files (
                file_id TEXT PRIMARY KEY,
                campaign_id TEXT,
                uploaded_by TEXT NOT NULL,
                original_name TEXT NOT NULL,
                extension TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
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
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        claim_columns = {row[1] for row in conn.execute("PRAGMA table_info(claims)")}
        if "download_token_hash" not in claim_columns:
            conn.execute("ALTER TABLE claims ADD COLUMN download_token_hash TEXT")
        if "download_token_expires_at" not in claim_columns:
            conn.execute("ALTER TABLE claims ADD COLUMN download_token_expires_at REAL")
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
        if "resource_file_id" not in campaign_columns:
            conn.execute("ALTER TABLE campaigns ADD COLUMN resource_file_id TEXT")
        creator_columns = {row[1] for row in conn.execute("PRAGMA table_info(creators)")}
        if "invite_approved" not in creator_columns:
            # Existing prototype accounts were created via open signup; require admin re-approval.
            conn.execute("ALTER TABLE creators ADD COLUMN invite_approved INTEGER NOT NULL DEFAULT 0")
        # Cover the lookups used by downloads, studio listings and claim counters.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_campaign ON claims(campaign_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_download_token ON claims(download_token_hash)")
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
    resourceType: Literal["link", "text", "file"] = "link"
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
    resourceType: Literal["link", "text", "file"] = "link"
    resource: str = Field(min_length=1, max_length=5000)
    video: str = Field(min_length=10, max_length=500)
    initials: str = Field(default='CR', max_length=4)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True, "verification": "youtube-comment-downloader"}


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
        except sqlite3.IntegrityError as exc:
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
            rows = conn.execute("SELECT c.campaign_id,c.title,c.channel,c.handle,c.category,c.accent,c.claimed,c.max_claims,c.ends_at,c.status,c.description,c.video_url,c.initials,c.resource_url,c.resource_type,c.resource_text,c.resource_file_id,rf.original_name AS resource_file_name,c.created_at FROM campaigns c LEFT JOIN resource_files rf ON rf.file_id=c.resource_file_id ORDER BY c.created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT c.campaign_id,c.title,c.channel,c.handle,c.category,c.accent,c.claimed,c.max_claims,c.ends_at,c.status,c.description,c.video_url,c.initials,c.resource_url,c.resource_type,c.resource_text,c.resource_file_id,rf.original_name AS resource_file_name,c.created_at FROM campaigns c LEFT JOIN resource_files rf ON rf.file_id=c.resource_file_id WHERE c.creator_email = ? ORDER BY c.created_at DESC", (user["email"],)).fetchall()
    return [dict(row) for row in rows]


def stored_resource_path(file_id: str, extension: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,40}", file_id) or extension not in ALLOWED_RESOURCE_TYPES:
        raise HTTPException(404, "Resource file not found.")
    return UPLOAD_DIR / f"{file_id}{extension}"


def safe_upload_name(raw_name: str, extension: str) -> str:
    name = unquote(raw_name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    name = re.sub(r"[^\w .()\-]", "_", name, flags=re.UNICODE)[:140].strip(" .")
    if not name or Path(name).suffix.lower() != extension:
        name = f"resource{extension}"
    return name


def validate_resource_file(conn, file_id: str, user: dict, campaign_id: str | None = None):
    row = conn.execute("SELECT * FROM resource_files WHERE file_id = ?", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Upload the resource file before saving the campaign.")
    if user["role"] != "admin" and row["uploaded_by"] != user["email"]:
        raise HTTPException(403, "You do not have access to that uploaded file.")
    if row["campaign_id"] not in (None, campaign_id):
        raise HTTPException(409, "That file is already attached to another campaign.")
    if not stored_resource_path(row["file_id"], row["extension"]).is_file():
        raise HTTPException(410, "The uploaded file is missing from storage. Upload it again.")
    return row


@app.post("/api/resources/upload")
async def upload_resource(request: Request, user=Depends(require_user)):
    raw_name = request.headers.get("x-file-name", "")
    if not raw_name:
        raise HTTPException(400, "Choose a file to upload.")
    decoded_name = unquote(raw_name).replace("\\", "/").split("/")[-1]
    extension = Path(decoded_name).suffix.lower()
    if extension not in ALLOWED_RESOURCE_TYPES:
        raise HTTPException(415, "Choose a PDF, Office document, text, CSV, ZIP, or image file.")
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        content_length = 0
    if content_length > MAX_RESOURCE_BYTES:
        raise HTTPException(413, "Files must be 15 MB or smaller.")

    file_id = secrets.token_urlsafe(18)
    path = stored_resource_path(file_id, extension)
    size = 0
    prefix = bytearray()
    try:
        with path.open("xb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_RESOURCE_BYTES:
                    raise HTTPException(413, "Files must be 15 MB or smaller.")
                if len(prefix) < 16:
                    prefix.extend(chunk[:16 - len(prefix)])
                output.write(chunk)
        if size == 0:
            raise HTTPException(400, "The selected file is empty.")
        if extension == ".pdf" and not bytes(prefix).startswith(b"%PDF-"):
            raise HTTPException(415, "The file does not appear to be a valid PDF.")
        if extension == ".png" and not bytes(prefix).startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(415, "The file does not appear to be a valid PNG image.")
        if extension in {".jpg", ".jpeg"} and not bytes(prefix).startswith(b"\xff\xd8\xff"):
            raise HTTPException(415, "The file does not appear to be a valid JPEG image.")
        if extension == ".webp" and (len(prefix) < 12 or bytes(prefix[:4]) != b"RIFF" or bytes(prefix[8:12]) != b"WEBP"):
            raise HTTPException(415, "The file does not appear to be a valid WebP image.")
        if extension in {".zip", ".docx", ".xlsx", ".pptx"} and not bytes(prefix).startswith(b"PK"):
            raise HTTPException(415, "The file does not appear to be a valid ZIP-based document.")
        filename = safe_upload_name(raw_name, extension)
        with closing(db()) as conn:
            conn.execute("INSERT INTO resource_files(file_id,campaign_id,uploaded_by,original_name,extension,media_type,size_bytes) VALUES(?,NULL,?,?,?,?,?)", (file_id,user["email"],filename,extension,ALLOWED_RESOURCE_TYPES[extension],size))
            conn.commit()
        return {"fileId": file_id, "fileName": filename, "sizeBytes": size, "contentType": ALLOWED_RESOURCE_TYPES[extension]}
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.delete("/api/resources/upload/{file_id}")
def delete_pending_resource(file_id: str, user=Depends(require_user)):
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM resource_files WHERE file_id = ?", (file_id,)).fetchone()
        if not row:
            return {"ok": True}
        if row["campaign_id"] is not None:
            raise HTTPException(409, "This file is attached to a campaign.")
        if user["role"] != "admin" and row["uploaded_by"] != user["email"]:
            raise HTTPException(403, "You do not have access to that uploaded file.")
        conn.execute("DELETE FROM resource_files WHERE file_id = ?", (file_id,))
        conn.commit()
    stored_resource_path(row["file_id"], row["extension"]).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/youtube/info")
def youtube_video_info(payload: VideoInfoRequest, user=Depends(require_user)):
    video_id = extract_video_id(payload.video)
    cached = cached_video_info(video_id)
    if cached is not None:
        return cached
    oembed_url = f"https://www.youtube.com/oembed?url={quote(f'https://www.youtube.com/watch?v={video_id}', safe='')}&format=json"
    request = UrlRequest(oembed_url, headers={"User-Agent": "Dropnote/1.0 (+video metadata preview)"})
    try:
        with urlopen(request, timeout=10) as response:
            info = json.load(response)
    except HTTPError as exc:
        if exc.code in (400, 401, 403, 404):
            raise HTTPException(422, "YouTube could not find public video details for that link.") from exc
        raise HTTPException(502, "YouTube video details are temporarily unavailable.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
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
            if payload.resourceType == "file":
                validate_resource_file(conn, payload.resource, user)
            conn.execute("""
                INSERT INTO campaigns(campaign_id,title,channel,handle,category,accent,claimed,max_claims,ends_at,status,description,resource_url,resource_type,resource_text,resource_file_id,video_url,initials,creator_email)
                VALUES(?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?)
            """, (payload.id,payload.title,payload.channel,payload.handle,payload.category,payload.accent,payload.limit,payload.ends,payload.status,payload.description,payload.resource if payload.resourceType == "link" else "",payload.resourceType,payload.resource if payload.resourceType == "text" else "",payload.resource if payload.resourceType == "file" else None,payload.video,payload.initials,user["email"]))
            if payload.resourceType == "file":
                conn.execute("UPDATE resource_files SET campaign_id = ? WHERE file_id = ?", (payload.id,payload.resource))
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise HTTPException(409, "That campaign ID already exists.") from exc
    return {"ok": True, "campaignId": payload.id}


@app.put("/api/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, payload: CampaignUpdate, user=Depends(require_user)):
    extract_video_id(payload.video)
    if payload.resourceType == "link" and not payload.resource.startswith(("https://", "http://")):
        raise HTTPException(400, "Enter a valid resource URL.")
    old_file_to_remove = None
    with closing(db()) as conn:
        existing = conn.execute("SELECT creator_email,claimed,resource_file_id FROM campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Campaign not found.")
        if user["role"] != "admin" and existing["creator_email"] != user["email"]:
            raise HTTPException(403, "You do not have access to this campaign.")
        if payload.limit is not None and payload.limit < existing["claimed"]:
            raise HTTPException(409, "Claim limit cannot be lower than the number already claimed.")
        conn.execute("BEGIN IMMEDIATE")
        new_file_id = payload.resource if payload.resourceType == "file" else None
        if new_file_id:
            validate_resource_file(conn, new_file_id, user, campaign_id)
        old_file_id = existing["resource_file_id"]
        if old_file_id and old_file_id != new_file_id:
            old_file_to_remove = conn.execute("SELECT * FROM resource_files WHERE file_id = ?", (old_file_id,)).fetchone()
            conn.execute("DELETE FROM resource_files WHERE file_id = ?", (old_file_id,))
        conn.execute("""
            UPDATE campaigns SET title=?,channel=?,handle=?,category=?,accent=?,max_claims=?,ends_at=?,status=?,description=?,
                resource_url=?,resource_type=?,resource_text=?,resource_file_id=?,video_url=?,initials=? WHERE campaign_id=?
        """, (payload.title,payload.channel,payload.handle,payload.category,payload.accent,payload.limit,payload.ends,payload.status,payload.description,
              payload.resource if payload.resourceType == "link" else "",payload.resourceType,payload.resource if payload.resourceType == "text" else "",new_file_id,payload.video,payload.initials,campaign_id))
        if new_file_id:
            conn.execute("UPDATE resource_files SET campaign_id = ? WHERE file_id = ?", (campaign_id,new_file_id))
        conn.commit()
    if old_file_to_remove:
        stored_resource_path(old_file_to_remove["file_id"],old_file_to_remove["extension"]).unlink(missing_ok=True)
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
        campaign = conn.execute("SELECT creator_email,resource_file_id FROM campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not campaign:
            raise HTTPException(404, "Campaign not found.")
        if user["role"] != "admin" and campaign["creator_email"] != user["email"]:
            raise HTTPException(403, "You do not have access to this campaign.")
        file_row = conn.execute("SELECT * FROM resource_files WHERE file_id = ?", (campaign["resource_file_id"],)).fetchone() if campaign["resource_file_id"] else None
        if file_row:
            conn.execute("DELETE FROM resource_files WHERE file_id = ?", (file_row["file_id"],))
        conn.execute("DELETE FROM claims WHERE campaign_id = ?", (campaign_id,))
        conn.execute("DELETE FROM campaigns WHERE campaign_id = ?", (campaign_id,))
        conn.commit()
    if file_row:
        stored_resource_path(file_row["file_id"],file_row["extension"]).unlink(missing_ok=True)
    return {"ok": True, "campaignId": campaign_id}


@app.get("/api/campaigns/{campaign_id}/resource-file")
def download_campaign_resource(campaign_id: str, x_resource_token: str = Header(default="")):
    if not x_resource_token:
        raise HTTPException(401, "Verify your comment before downloading this resource.")
    token_hash = hashlib.sha256(x_resource_token.encode()).hexdigest()
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT rf.file_id,rf.extension,rf.original_name
            FROM campaigns c
            JOIN resource_files rf ON rf.file_id = c.resource_file_id
            JOIN claims cl ON cl.campaign_id = c.campaign_id
            WHERE c.campaign_id = ? AND cl.download_token_hash = ? AND cl.download_token_expires_at >= ?
        """, (campaign_id,token_hash,time.time())).fetchone()
    if not row:
        raise HTTPException(403, "This download link is invalid or expired. Verify your comment again to get a fresh download.")
    path = stored_resource_path(row["file_id"],row["extension"])
    if not path.is_file():
        raise HTTPException(410, "This resource file is no longer available.")
    return FileResponse(path,filename=row["original_name"],media_type="application/octet-stream",headers={"X-Content-Type-Options":"nosniff","Cache-Control":"private, no-store"})


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
    resource_file_name = None
    if campaign["resource_type"] == "file":
        with closing(db()) as conn:
            file_row = conn.execute("SELECT original_name,extension FROM resource_files WHERE file_id = ? AND campaign_id = ?", (campaign["resource_file_id"],payload.campaignId)).fetchone()
        if not file_row or not stored_resource_path(campaign["resource_file_id"],file_row["extension"]).is_file():
            raise HTTPException(410, "This resource file is no longer available.")
        resource_file_name = file_row["original_name"]

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

    download_token = secrets.token_urlsafe(32) if campaign["resource_type"] == "file" else None
    download_token_hash = hashlib.sha256(download_token.encode()).hexdigest() if download_token else None
    download_token_expires_at = time.time() + RESOURCE_TOKEN_SECONDS if download_token else None
    try:
        with closing(db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute("SELECT claimed, max_claims, status, ends_at, resource_type, resource_file_id FROM campaigns WHERE campaign_id = ?", (payload.campaignId,)).fetchone()
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
            if latest["resource_type"] != campaign["resource_type"] or latest["resource_file_id"] != campaign["resource_file_id"]:
                raise HTTPException(409, "The campaign resource changed while this claim was being checked. Please try again.")
            existing = conn.execute(
                "SELECT campaign_id FROM claims WHERE video_id = ? AND author_channel_id = ?",
                (video_id, author_channel),
            ).fetchone()
            if existing:
                if existing["campaign_id"] != payload.campaignId:
                    raise HTTPException(409, "This YouTube account has already claimed a drop for this video.")
                # Idempotent re-verification restores access after session storage is cleared.
                conn.execute("UPDATE claims SET download_token_hash = ?, download_token_expires_at = ? WHERE video_id = ? AND author_channel_id = ?", (download_token_hash,download_token_expires_at,video_id,author_channel))
                already_claimed = True
            else:
                if latest["max_claims"] and latest["claimed"] >= latest["max_claims"]:
                    raise HTTPException(410, "This campaign has reached its claim limit.")
                conn.execute(
                    "INSERT INTO claims(campaign_id, video_id, author_channel_id, comment_id, download_token_hash, download_token_expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (payload.campaignId, video_id, author_channel, comment_id,download_token_hash,download_token_expires_at),
                )
                conn.execute("UPDATE campaigns SET claimed = claimed + 1 WHERE campaign_id = ?", (payload.campaignId,))
                already_claimed = False
            conn.commit()
    except sqlite3.IntegrityError as exc:
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
        "downloadToken": download_token,
        "resourceFileName": resource_file_name,
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
