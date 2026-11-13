# Dropnote

Dropnote is an open-source prototype for creator campaigns that unlock a resource after a viewer posts a matching claim sentence as a comment on a linked YouTube video or Short.

> **Prototype notice:** The verification flow scrapes public YouTube comments and is best-effort. This project is not production-ready; review YouTube policies and the security, privacy, and persistence limitations below before using it with real users or valuable resources.

## Features

- Responsive React and Material UI interface with light, dark, and system themes.
- Creator Studio with campaign creation, editing, pause/resume, deletion, and campaign-specific share links.
- Link, text, and private file resources. File uploads are limited to 15 MB and common document, text, archive, and image formats. Files are offered for download only after comment verification.
- Viewer-written comments with a generated claim sentence appended only when the viewer copies the comment.
- Invite-only creator accounts. The admin creates email-bound, single-use invitation links; email delivery is not built in, so links are shared manually.
- SQLite persistence for local accounts, sessions, campaigns, and claims.

## Requirements

- Node.js 20 or later and npm.
- Python 3.12 or later.

## Run locally

### 1. Install dependencies

```bash
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows, use `.venv\\Scripts\\python -m pip install -r requirements.txt`.

### 2. Configure the local admin

```bash
cp .env.example .env
```

Edit `.env` and set a real local admin email and a long, unique password. Do not use the example values in a deployed environment. Load the variables in the terminal that will run the API:

```bash
set -a
. ./.env
set +a
```

PowerShell users can set the variables for the current terminal instead:

```powershell
$env:DROPNOTE_ADMIN_EMAIL = "admin@example.test"
$env:DROPNOTE_ADMIN_PASSWORD = "replace-with-a-long-unique-password"
$env:DROPNOTE_COOKIE_SECURE = "false"
```

### 3. Start the API and frontend

In one terminal:

```bash
.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
```

In a second terminal:

```bash
npm run dev
```

Open the Vite URL printed in the second terminal (normally `http://localhost:5173`). Vite proxies `/api` requests to the API on port 8000. FastAPI's interactive API documentation is at `http://localhost:8000/docs`.

Sign in to **Studio** with the environment-configured admin credentials. Use **Invite creator** to generate an email-bound link, then share that link privately with the intended person. There is no public creator signup.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `DROPNOTE_ADMIN_EMAIL` | Environment-configured administrator email | Unset; admin login unavailable |
| `DROPNOTE_ADMIN_PASSWORD` | Environment-configured administrator password | Unset; admin login unavailable |
| `DROPNOTE_COOKIE_SECURE` | Force Secure session cookies (`true` in HTTPS deployments) | Automatically inferred from request/proxy |
| `DROPNOTE_DB` | SQLite database file | `dropnote.sqlite3` in the working directory |
| `DROPNOTE_UPLOAD_DIR` | Private directory for resource files | `dropnote-uploads` beside the database |
| `MAX_SCAN_COMMENTS` | Maximum recent comments examined during a check | `250` |
| `COMMENT_CACHE_TTL` | Seconds a scraped comment page is reused; concurrent checks share one scrape | `15` |
| `COMMENT_CACHE_MAX_VIDEOS` | Maximum videos kept in the comment cache | `64` |
| `VIDEO_INFO_CACHE_TTL` | Seconds YouTube video metadata is cached in Studio | `600` |

Never commit `.env`, real credentials, session cookies, invitation codes, database files, or user uploads. The repository includes `.env.example` with placeholders only.

## Performance notes

- The newest comments for a video are scraped once and reused for `COMMENT_CACHE_TTL` seconds, and parallel checks for the same video share a single scrape. Repeat checks drop from a multi-second network round trip to a few microseconds, which also reduces the chance of YouTube rate limiting. A comment posted within that cache window may need a retry; lower the TTL if that matters for your campaign.
- SQLite runs in WAL mode with indexes for claim lookups, so downloads and campaign pages are not blocked while a claim is written.
- Hashed Vite assets are served with a one-year `immutable` cache, and API responses are marked `no-store`.
- The Docker image runs as a non-root user and pre-compiles `server.py` so the first request after a cold start is faster.

## File resources

Creators choose **Downloadable file** in the campaign form and select an allowed file of at most 15 MB. Uploads are written outside the public static directory. After verification, the API returns a short-lived download token; the download endpoint requires that token and serves the file as an attachment. The token and unlocked resource are kept in the browser session, not in local persistent browser storage. Back up the upload directory together with the database, and configure both on durable private storage for deployments.

## Tests and build

```bash
npm ci
npm run build
python -m py_compile server.py
python -m unittest discover -s tests -v
```

GitHub Actions runs these checks for pushes and pull requests.

## Docker

Build the combined frontend/API image:

```bash
docker build -t dropnote .
```

Run it with private environment variables and a persistent volume for the SQLite database and uploads:

```bash
docker run --rm -p 10000:10000 \
  -e DROPNOTE_ADMIN_EMAIL='admin@example.com' \
  -e DROPNOTE_ADMIN_PASSWORD='use-a-long-unique-secret' \
  -e DROPNOTE_COOKIE_SECURE=true \
  -e DROPNOTE_DB=/data/dropnote.sqlite3 \
  -e DROPNOTE_UPLOAD_DIR=/data/dropnote-uploads \
  -v dropnote-data:/data \
  dropnote
```

The included `render.yaml` is a convenience for a **temporary test deployment**. Free/ephemeral hosts can sleep and may discard local databases and uploaded files. Do not rely on such a deployment for durable user accounts, campaigns, claims, or resources; use persistent storage and a managed database before hosting real users.

## GitHub publishing checklist

1. Create a new empty repository on GitHub and choose its visibility. Do not add a generated README or license there; this project already includes both.
2. From the project directory, review the files that will be committed. `.gitignore` excludes local databases, `.env` files, uploads, builds, screenshots, and generated preview bundles.
3. Initialize and push the repository:

   ```bash
   git init -b main
   git add .
   git status --short
   git diff --cached --stat
   git commit -m "Prepare Dropnote for open-source release"
   git remote add origin https://github.com/YOUR-USERNAME/dropnote.git
   git push -u origin main
   ```

4. Replace `YOUR-USERNAME` with the repository owner. In GitHub, enable private vulnerability reporting and review the repository description, topics, and default branch.
5. If deploying, configure admin credentials and durable database/file storage as server-side secrets/settings. Never put production secrets in GitHub source or frontend variables.

If this folder is already a Git repository, inspect `git status` and remotes before initializing or pushing; do not overwrite an existing history.

## Limitations and production cautions

- `youtube-comment-downloader` scrapes public YouTube web responses rather than using a stable supported YouTube API. YouTube can change or block it; verification can fail, be rate-limited, or miss comments outside the scan window. Review its license and YouTube's terms and policies before deployment.
- The “comment to unlock” mechanic may conflict with YouTube fake-engagement rules. Review current platform policies and obtain qualified advice before public use.
- Email ownership is not independently verified during creator signup. A private invitation link is bound to an email string, but the prototype does not prove the registrant controls that inbox.
- There is no email sending, account recovery, CAPTCHA, or distributed login/signup rate limiting. The optional recovery email field is display-only and is not sent to or saved by the backend.
- SQLite and local file storage are suitable only for local use or temporary demos. Configure durable storage, backups, retention controls, and appropriate access controls before using real user data.
- A YouTube channel ID identifies an account/channel, not a unique human; one person can use multiple YouTube accounts.

## License

MIT. See [LICENSE](LICENSE).
