# Dropnote

Dropnote is an open-source prototype for creator campaigns that unlock a resource after a viewer posts a matching claim sentence as a comment on a linked YouTube video or Short.

> **Prototype notice:** The verification flow scrapes public YouTube comments and is best-effort. This project is not production-ready; review YouTube policies and the security, privacy, and persistence limitations below before using it with real users or valuable resources.

## Features

- Responsive React and Material UI interface with light, dark, and system themes.
- Creator Studio with campaign creation, editing, pause/resume, deletion, and campaign-specific share links.
- Bulk campaign management: easily pause all, resume all, or select multiple campaigns to pause, resume, or delete.
- Link or plain-text resources. The link or text is returned only after comment verification and is revealed in the viewer's browser; nothing is uploaded or stored as a file.
- Viewer-written comments with a generated claim sentence appended only when the viewer copies the comment.
- Private, zero-email claiming flow where unlocked resources live securely in the browser's session storage.
- Flexible database persistence supporting both local SQLite and cloud PostgreSQL (e.g. Neon Serverless Postgres) with connection pooling.
- Strong password security using PBKDF2-HMAC-SHA256 with 310,000 rounds and random per-user salts.

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

Sign in to **Studio** with the environment-configured admin credentials to create, manage, and monitor your campaigns.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string (e.g. Neon Serverless Postgres); enables PostgreSQL persistence and connection pooling | Unset; falls back to SQLite |
| `DROPNOTE_ADMIN_EMAIL` | Environment-configured administrator email | Unset; admin login unavailable |
| `DROPNOTE_ADMIN_PASSWORD` | Environment-configured administrator password | Unset; admin login unavailable |
| `DROPNOTE_COOKIE_SECURE` | Force Secure session cookies (`true` in HTTPS deployments) | Automatically inferred from request/proxy |
| `DROPNOTE_DB` | SQLite database file (used when `DATABASE_URL` is unset) | `dropnote.sqlite3` in the working directory |
| `MAX_SCAN_COMMENTS` | Maximum recent comments examined during a check | `250` |
| `COMMENT_CACHE_TTL` | Seconds a scraped comment page is reused; concurrent checks share one scrape | `15` |
| `COMMENT_CACHE_MAX_VIDEOS` | Maximum videos kept in the comment cache | `64` |
| `VIDEO_INFO_CACHE_TTL` | Seconds YouTube video metadata is cached in Studio | `600` |

Never commit `.env`, real credentials, session cookies, invitation codes, or database files. The repository includes `.env.example` with placeholders only.

## Performance notes

- The newest comments for a video are scraped once and reused for `COMMENT_CACHE_TTL` seconds, and parallel checks for the same video share a single scrape. Repeat checks drop from a multi-second network round trip to a few microseconds, which also reduces the chance of YouTube rate limiting. A comment posted within that cache window may need a retry; lower the TTL if that matters for your campaign.
- SQLite runs in WAL mode with indexes for claim lookups, so campaign pages stay readable while a claim is written.
- Hashed Vite assets are served with a one-year `immutable` cache, and API responses are marked `no-store`.
- The Docker image runs as a non-root user and pre-compiles `server.py` so the first request after a cold start is faster.

## How resources are delivered

Creators choose **Link** or **Text** in the campaign form. The link or text is stored as campaign configuration and is never included in the public campaign list; the API returns it only from `/api/verify` after a matching comment is found. The viewer then opens the link or copies/saves the text entirely in the browser. There is no upload endpoint, no file storage directory, and no download token, so a deployment only needs durable storage for the small SQLite database.

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

Run it with private environment variables and a persistent volume for the SQLite database:

```bash
docker run --rm -p 10000:10000 \
  -e DROPNOTE_ADMIN_EMAIL='admin@example.com' \
  -e DROPNOTE_ADMIN_PASSWORD='use-a-long-unique-secret' \
  -e DROPNOTE_COOKIE_SECURE=true \
  -e DROPNOTE_DB=/data/dropnote.sqlite3 \
  -v dropnote-data:/data \
  dropnote
```

## Free deployment (Render + Neon PostgreSQL)

You can deploy Dropnote completely for free using **[Render](https://render.com)** for web hosting and **[Neon](https://neon.tech)** for serverless PostgreSQL. This combination provides zero-cost hosting with durable cloud database persistence across server restarts and new builds.

### Step 1: Create a free PostgreSQL database on Neon

1. Sign up for a free account at [neon.tech](https://neon.tech).
2. Click **Create Project** and name it (for example, `dropnote`).
3. Neon will display your **Connection Details**.
4. Copy the connection string (format: `postgresql://<user>:<password>@<endpoint>.neon.tech/neondb?sslmode=require`).
   * Dropnote connects directly using this URL and manages connection pooling with `psycopg_pool`.

### Step 2: Deploy to Render for free

You can deploy using either the **Render Blueprint** (automatic) or **Manual Web Service Setup**:

#### Option A: One-click Blueprint Deploy (Recommended)
1. Fork or push this repository to your GitHub account.
2. Sign in to your [Render Dashboard](https://dashboard.render.com).
3. Click **New +** and select **Blueprint**.
4. Connect your GitHub repository. Render automatically reads the included `render.yaml` configuration.
5. In the environment variables prompt, enter:
   * `DATABASE_URL`: Your Neon PostgreSQL connection string.
   * `DROPNOTE_ADMIN_EMAIL`: Your administrator email (for example, `admin@yourdomain.com`).
   * `DROPNOTE_ADMIN_PASSWORD`: A secure password for Studio administrator access.
6. Click **Apply**. Render will build the Docker container and start your service on the Free plan.

#### Option B: Manual Web Service Setup
1. Sign in to your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** and select **Web Service**.
3. Connect your GitHub repository.
4. Configure the service settings:
   * **Name**: `dropnote` (or your preferred name)
   * **Runtime**: `Docker` (Render automatically uses the included multi-stage `Dockerfile`)
   * **Instance Type**: `Free`
5. Under **Environment Variables**, add:
   * `DATABASE_URL`: Your Neon PostgreSQL connection string (`postgresql://...`).
   * `DROPNOTE_ADMIN_EMAIL`: Your administrator email.
   * `DROPNOTE_ADMIN_PASSWORD`: A secure administrator password.
   * `DROPNOTE_COOKIE_SECURE`: `true` (Render provides free automatic HTTPS).
   * `PORT`: `10000` (Render default).
6. Click **Create Web Service**.

### Step 3: Verify and access your deployment

1. Render compiles the Vite frontend (`npm run build`) and packages it into the Python container.
2. On initial startup, Dropnote automatically creates the required PostgreSQL schema (`campaigns`, `claims`, `creators`, `creator_invites`, and `sessions`) in your Neon database.
3. Once the build status displays `Live`, open your Render URL (for example, `https://dropnote.onrender.com`).
4. Navigate to `/studio` to sign in with your configured admin email and password.
5. You can now manage campaigns, pause or resume drops in bulk, and invite other creators!

> **Free Tier Spin-Down:** Free Render web services spin down after 15 minutes of inactivity. When a new visitor opens the link, Render wakes up the service in approximately 30–50 seconds. Because your database is hosted on Neon, all campaigns, claims, and creator accounts remain completely safe and persistent.

## GitHub publishing checklist

1. Create a new empty repository on GitHub and choose its visibility. Do not add a generated README or license there; this project already includes both.
2. From the project directory, review the files that will be committed. `.gitignore` excludes local databases, `.env` files, builds, screenshots, and generated preview bundles.
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
5. If deploying, configure admin credentials and durable database storage as server-side secrets/settings. Never put production secrets in GitHub source or frontend variables.

If this folder is already a Git repository, inspect `git status` and remotes before initializing or pushing; do not overwrite an existing history.

## Limitations and production cautions

- `youtube-comment-downloader` scrapes public YouTube web responses rather than using a stable supported YouTube API. YouTube can change or block it; verification can fail, be rate-limited, or miss comments outside the scan window. Review its license and YouTube's terms and policies before deployment.
- The “comment to unlock” mechanic may conflict with YouTube fake-engagement rules. Review current platform policies and obtain qualified advice before public use.
- Email ownership is not independently verified during creator signup. A private invitation link is bound to an email string, but the prototype does not prove the registrant controls that inbox.
- There is no viewer email collection, tracking, or account registration required. The claim and unlock flow is completely private and runs client-side in session storage.
- When running with SQLite, persistence is suitable only for local use or temporary demos. For durable production storage across deployments, use a managed PostgreSQL database such as Neon (documented in the Free Deployment section above).
- A YouTube channel ID identifies an account/channel, not a unique human; one person can use multiple YouTube accounts.

## License

MIT. See [LICENSE](LICENSE).
