# Sift (Inbox Agent) — Progress Log

Read `CLAUDE.md` first, then this file. Spec: `Inbox_Agent_Master_Prompt.md`.
Rule: commit every change to git, never push (the owner pushes).

## Project
- Name: **Sift** (repo `jeelnadaa/sift`). Spec calls it "Inbox Agent".
- Domain: solarquack.in, default subdomain `sift.solarquack.in`.

## Status
| Track | State |
|-------|-------|
| Design (landing, web UI, mobile) | Approved by owner (v2 + font fix). See `DESIGN.md`, `design/README.md` |
| Phase 0 (setup) | **Accepted 2026-10-24** on the owner's laptop (native Windows, Postgres queue, poll mode). Both checks passed |
| Phase 1 (notification pipeline) | Not started. Waiting for the owner's go-ahead and the Phase 1 decisions under Open questions |
| Phases 2–5 | Not started |

## Log (newest last)
- 2026-10-24 — Chose name Sift. Started design track: static HTML prototypes in `design/`.
- 2026-10-24 — Design v1 built: shared tokens/components, landing page (motion), web UI (13 routes), mobile gallery (20 screens). Verified over local http server, no console errors.
- 2026-10-24 — Design v2 (owner feedback): Satoshi for all UI text and tabular numerals instead of monospace (JetBrains Mono only for real code); radii cut to 4/6/8/10/14 (no pills); all pill text capitalized, snake_case removed; web sidebar collapsible (264/76px, `[` key, persisted) with labeled sections Inbox/Organize/Control/Account and SVG icons; removed the AI-on sidebar pill; wordmark and heading tracking opened up; same changes on mobile and landing; themed scrollbars. Wrote `DESIGN.md`.
- 2026-10-24 — Fixed Satoshi not loading (Fontshare returned only Clash Display for a combined request). Fonts self-hosted in `design/shared/fonts/`. Added `CLAUDE.md` with all standing instructions.
- 2026-10-24 — Owner approved the design. **Phase 0 implemented:**
  - `backend/`: FastAPI app (`/health`, `POST /webhooks/gmail`, `POST /api/v1/devices`, `POST /api/v1/dev/test-push`), settings via env, Fernet encryption with key rotation, Pub/Sub OIDC verification (signature/aud/exp via google-auth, plus iss/email/email_verified), FCM HTTP v1 client (data-only, `android.priority=high`, UNREGISTERED → delete token), queue with two backends (arq/Redis, or Postgres `jobs` table with SKIP LOCKED + backoff + stale-lock reclaim), worker entrypoint, CLI (`create-user`, `gen-key`, `fake-push`).
  - Full data model from brief §12 (24 tables) in Alembic migration `0001`. Up/down/up verified.
  - 38 tests pass (pubsub auth + parsing, webhook, dedupe, FCM message/errors, queue retry, crypto rotation, health, devices, test-push). Tests build the schema through the real migration.
  - End-to-end run (uvicorn + Postgres worker): fake push → 204 → job → worker routed to account; redelivery deduped; unknown address handled.
  - `docker-compose.yml` (postgres, redis[profile], api, worker, caddy[profile]), `deploy/Caddyfile`, `backend/Dockerfile`, `.env.example`, `scripts/backup.sh` + `restore.sh`.
  - `android/`: minimal Compose app `com.solarquack.sift` — FCM token display/copy, notification channels per tier (urgent/normal/digest), data-message handler that shows the notification and measures delay, notification permission and battery-exemption status. `assembleDebug` builds.
  - `README.md`: exact setup (GCP, Pub/Sub, OAuth consent, Firebase, Android, Oracle VM, env, acceptance checks, local dev, backups, rebuild, reclaim risk, cost alerts).
- 2026-10-24 — Owner could not set up Google Pub/Sub (needs a billed project) and will host on the laptop first (Cloudflare Tunnel), Oracle later. **Phase 0 reworked:**
  - New-mail detection is now pluggable: `CHANGE_DETECTION=poll` (default; scheduler queues `check_account` every `POLL_INTERVAL_SECONDS`=10) or `push` (Gmail watch + Pub/Sub webhook, kept intact). Both feed the same `accounts.check_account()` (history.list from stored cursor, row lock, cursor saved only after processing). Push mode keeps a 5-minute safety poll and renews watches daily.
  - Pulled forward from Phase 1 (needed to prove detection): `MailProvider` interface (`app/mail/base.py`), Gmail REST client (`app/mail/gmail.py`), OAuth web flow with HMAC-signed state (`app/mail/google_oauth.py`), `/api/v1/accounts/connect-url`, `/api/v1/accounts/oauth/callback` (HTML result page), `/api/v1/accounts`. Read-only scope. invalid_grant → needs_reconnect; admin policy → blocked; unreadable token (key changed) → needs_reconnect.
  - New `scheduler` process (`python -m app.scheduler`) and Compose service; `cloudflared` Compose profile; `scripts/run-local.ps1` for native Windows (no Docker, Postgres queue).
  - Migration `0002`: jobs dedupe only while queued/running (partial unique index) so recurring checks never pile up; hourly cleanup of finished jobs. arq `keep_result=0` for the same reason.
  - CLI: `connect-url`, `accounts`, `check`.
  - 72 tests pass. `run-local.ps1` run end to end with fake credentials: API healthy, scheduler queues checks, worker runs them, failures back off as one job.
  - README rewritten: laptop first (native or Docker Desktop), Cloudflare Tunnel, acceptance checks, "Move to Oracle", optional Pub/Sub.
- 2026-10-24 — Owner can enable Pub/Sub and has separate Google and Firebase projects. Documented: Pub/Sub goes in the Gmail/OAuth project; Firebase may be separate. Still on poll mode until the owner switches (needs billing + stable tunnel hostname).
- 2026-10-24 — **Phase 0 accepted** on the owner's laptop. Setup: native Windows via `scripts/run-local.ps1`, owner's Postgres 18 (`sift` user/db), `QUEUE_BACKEND=postgres`, `CHANGE_DETECTION=poll` (10 s), Google project `sift-quack` (OAuth client, Gmail API, Pub/Sub topic + push service account prepared but unused), Firebase project `sift-quack-firebase`. Owner account `jeelnadaa@gmail.com` created; Gmail `jeelnadaa@gmail.com` connected (read-only, active).
  - Check A: test email received by Gmail 06:14:15, detected by Sift 06:14:32 (**17.8 s**, one sample; poll interval 10 s plus Gmail history lag). Slower than the 5–10 s estimate.
  - Check B: device registered, FCM accepted the test push and the owner confirmed the notification arrived on the phone.
  - Fixed during setup: `.env` had `QUEUE_BACKEND=redis` (no Redis on the laptop) and empty `APP_SECRET`/`ENCRYPTION_KEYS`/`ADMIN_TOKEN`; set to postgres and random values. DB user password mismatch resolved by the owner.

## Decisions
- Designs are static HTML/CSS/JS prototypes; the visual reference for the React web UI and Compose app. Keep `DESIGN.md` in sync with any design change, in the same commit.
- Fonts: Clash Display (display), Satoshi (all UI text), self-hosted; JetBrains Mono only for code.
- **Defaults taken for Phase 0 (owner can change):**
  - Hosting (owner, 2026-10-24): **laptop first** (native Windows with the Postgres queue, or Docker Desktop), optional Cloudflare Tunnel; Oracle Always Free later (owner has a card but setup is pending). Host is chosen only by `.env`; README §6 is the migration path.
  - New-mail detection (owner, 2026-10-24): **poll by default**, Pub/Sub push must stay available as a switch (`CHANGE_DETECTION`). Never hard-wire either.
  - Subdomain: `sift.solarquack.in`.
  - Android package: `com.solarquack.sift` (not `in.solarquack.sift`: `in` is a Kotlin keyword and would need backticks in every file).
  - Owner has two projects: a Google Cloud project (Gmail API, OAuth client, and Pub/Sub when push is enabled) and a separate Firebase project (FCM only). Pub/Sub must live in the OAuth client's project (Gmail watch rejects topics from other projects).
- Postgres 17 in Docker. Python 3.12 in Docker (code also runs on 3.14 locally).
- Android toolchain pinned to versions already in the local Gradle cache: AGP 8.7.3, Kotlin 2.0.21, Gradle 8.11.1, Compose BOM 2024.12.01, Firebase BOM 33.7.0, compileSdk/targetSdk 35, minSdk 26. Upgrade deliberately later.
- Webhook acks malformed pushes with 204 (a non-2xx makes Pub/Sub retry forever) and refuses to run unverified in `ENV=prod`.
- Pub/Sub redeliveries are deduped by `push:<messageId>` (arq job id or `jobs.dedupe_key`).
- Phase 0 endpoints use a shared `ADMIN_TOKEN`; Phase 1 replaces this with JWT.
- `accounts.email` is globally unique because pushes carry only the address.
- `notifications.message_id` is unique so a message can never notify twice.

## Open questions (for the owner)
Phase 1 decisions (asked 2026-10-24):
1. Lower `POLL_INTERVAL_SECONDS` to 5 (measured 17.8 s at 10 s)? Costs ~24 of 6,000 Gmail quota units/min per account.
2. The phone app must reach the API in Phase 1: is `solarquack.in` on Cloudflare DNS (stable tunnel hostname such as `sift.solarquack.in`)?
3. App sign-in: email + password for the owner account (JWT), as the default?

## Known limitations (Phase 0)
- Docker Compose, Redis queue, Cloudflare Tunnel and push mode not run locally (no Docker, no credentials). Native + Postgres queue + poll mode verified end to end with fake Gmail credentials.
- Poll latency: measured 17.8 s end to end at a 10 s interval (one sample). Push mode or a shorter interval would be faster.
- History older than ~a week expires: Sift restarts from now (catch-up scan comes with the Phase 1 pipeline).
- Admin-token auth on account/device/dev endpoints until Phase 1 JWT.
- Android app: setup screen only; no custom fonts yet.

## Dev environment notes (this Windows machine)
- No Docker. Local Postgres 18 on :5432 needs the owner's password, so sessions use a throwaway cluster: `initdb -U sift -A trust` in the session scratchpad, started on **port 5433**, databases `sift` and `sift_test`. Recreate it if missing.
- Run tests: `cd backend && TEST_DATABASE_URL=postgresql+psycopg://sift@localhost:5433/sift_test .venv/Scripts/python -m pytest -q`.
- `scripts/run-local.ps1` must be started as its own process (`powershell -File ...`); it does not work inside a PowerShell background job (Start-Job).
- Gradle on Windows here fails with "Unable to establish loopback connection" unless `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:\gtmp` is set (and it must run outside the tool sandbox).
