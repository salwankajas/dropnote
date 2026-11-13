# Dropnote roadmap

Dropnote is currently an experimental prototype. The roadmap below describes work that should be completed before production use; it is not a promise of a release date.

## Before public production

1. **Platform and policy review:** confirm the proposed comment-conditioned resource flow is allowed under current YouTube policies. Remove or redesign it if necessary.
2. **Durable storage:** replace local SQLite accounts, sessions, campaigns, and claims with a managed database; add migrations, backups, and row-level authorization.
3. **Authentication and account lifecycle:** verify invitee identity, add secure recovery, rate limits, abuse controls, and account/session management.
4. **Privacy and operations:** publish privacy/retention terms, minimize stored data, define deletion and retention policies, add security logging and monitoring, and document incident handling.
5. **Deployment hardening:** configure secrets only in the host, enforce HTTPS and secure cookies, add request-size and rate limits, and test backup/restore and authorization boundaries.

## Known prototype limitations

- Comment verification uses best-effort scraping through `youtube-comment-downloader`, not a stable supported YouTube API.
- Email is not sent by the app. Creator invitations are created as email-bound links and must be shared manually.
- The optional recovery-email field is display-only; it is not sent to or stored by the backend.
- Local SQLite is not durable on many free hosting plans.
- A YouTube channel ID identifies a channel account, not a unique human.
