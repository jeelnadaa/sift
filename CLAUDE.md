# CLAUDE.md — Sift (Inbox Agent)

Guide for every Claude session on this repo. Read it fully before doing anything. It holds the owner's standing instructions.

## 1. What this project is
**Sift** is a personal email assistant (the spec calls it "Inbox Agent"): multi-account Gmail, rules first, an optional small LLM using the user's own API key, instant FCM push to Android, company timelines for placement mail, and over time a Gmail replacement. Repo: `jeelnadaa/sift`. Domain: `solarquack.in`.

> [!IMPORTANT]
> **Production Status: LIVE ON ORACLE CLOUD FREE TIER**
> Sift is **no longer running on the owner's laptop**. It is deployed and running 24/7 on an Oracle Cloud Free Tier instance (Ampere A1 Flex, Oracle Linux 9).
> Public domain: **`https://sift.solarquack.in`** (routed via Cloudflare Tunnel).
> See **Section 11: Production Environment & Deployment** below before making changes to production.

Full product spec and build phases: `Inbox_Agent_Master_Prompt.md`. That file is the source of truth for **what** to build.

## 2. Start of every session (do this first, in order)
1. Read this file.
2. Read `PROGRESS.md` for current status, the log (newest last), decisions and open questions.
3. Read `DESIGN.md` before touching anything visual.
4. Skim `Inbox_Agent_Master_Prompt.md`, especially the section for the current phase (section 14) and any section it references.
5. Run `git status` and `git log --oneline -10` to confirm the working tree matches `PROGRESS.md`.
6. Tell the owner in 2–3 lines where things stand, then continue. Do not re-ask things already decided in `PROGRESS.md`.

## 3. How to work
- **Production quality, always (owner, 2026-10-24).** Build everything as if Sift will be published for other users, even while the owner is the only user: real authentication and abuse protection, input validation, safe defaults, error handling, accessibility, tests. "Only one user today" is never a reason to cut a corner. Deployment choices come after the app is complete.
- **Phase by phase.** Build only the current phase from the master prompt (section 14). After each phase: run it, check every acceptance criterion, report what works and what does not, list known limitations, then **stop and wait for the owner's go-ahead** before the next phase.
- Before writing code for a phase, list the decisions you need from the owner as a short numbered list (hosting choice, package names, Firebase and Google Cloud details). Unresolved ones live in `PROGRESS.md` under Open questions.
- Keep it simple. Do not add features that are not in the brief.
- Check current Google, Firebase and Gmail docs before using an API detail you are not sure about. Do not guess.
- Only ask the owner when a decision is genuinely theirs. Otherwise pick a sensible default, say so, and move on.

## 4. Documentation and progress log (mandatory)
Everything you do must be documented so a fresh session can resume cold.
- `PROGRESS.md` is the running log. After every meaningful change append a dated line to **Log** (what changed and why), update the **Status** table, record new **Decisions**, and add or close **Open questions**.
- `README.md` holds exact setup steps once Phase 0 exists; keep it accurate.
- `DESIGN.md` is the design source of truth. Any visual change updates it **in the same commit**.
- `design/README.md` documents the prototypes and screen coverage.
- Explain non-obvious decisions briefly in code comments or the README.
- After each phase add a short **Known limitations** list.
- Never leave the docs describing something the code no longer does.

## 5. Git rules (mandatory)
- Every change is committed to git. Small, focused commits with clear messages. Update `PROGRESS.md` in the same commit as the work it describes.
- **Never `git push`.** The owner pushes. Never force-push, rewrite history, or amend commits unless asked.
- Commit only when the work is in a coherent, working state. Never commit secrets, `.env`, tokens or API keys; use `.env.example` instead.
- End commit messages with the Co-Authored-By line given in your session's attribution instructions.
- Before finishing a session, `git status` must be clean (everything committed).

## 6. Design rules (full detail in `DESIGN.md`)
- **Fonts:** Satoshi is the base font for all normal UI text, buttons, pills, tables, inputs, timestamps and numbers (use tabular numerals, not monospace). **Clash Display** is for headlines, page titles, the wordmark, big numbers and avatars. JetBrains Mono is only for real code (regex, Gmail query strings, API keys, model IDs). Fonts are self-hosted in `design/shared/fonts/` and declared in `design/shared/fonts.css`. Never load Satoshi and Clash from one Fontshare URL (it only returns the first family).
- **Shape:** small, consistent corners. Tokens: 4 / 6 / 8 / 10 / 14 px (`--r-xs … --r-xl`). No pill-shaped controls. Only dots and similar marks are circular.
- **Pill text** always starts with a capital letter and never shows snake_case (e.g. "Assessment link"). Gmail-syntax query chips such as `from:kotak` stay as typed.
- **Web sidebar:** collapsible (264px open, 76px icon rail), persisted, `[` key toggles. Sections with visual separation: Inbox, Organize, Control, Account. No "AI on" pill in the sidebar. Wordmark has open letter-spacing and spacing around the logo mark.
- **Mobile mirrors the web** for fonts, corners, pills and wordmark.
- Keep the dark theme, lime `--signal` accent, and one color per priority tier.
- Motion respects `prefers-reduced-motion`.
- After design changes, view the prototypes over HTTP and check them in the browser pane before committing:
  `cd design && python -m http.server 8765` then open `/landing/`, `/web/`, `/mobile/` (use `?v=N` to bust cache). Stop the server when done.
- Then polish: look for overflow, cramped spacing, uneven rows and inconsistent corners.

## 7. Product and safety rules (from the master prompt, never break these)
- **Bring your own key.** No shared or built-in LLM key. Store each user's key encrypted, never log or return it (only last 4 characters). One gate, `ai_enabled(user)`, guards every token-using path, with tests proving **no LLM call** is made when it is off. AI-off mode must keep everything else working and deliver unhandled mail as normal priority, never hidden.
- Treat all email content as untrusted. The agent is read-only by default; sending, deleting or modifying mail needs an explicit user action. Request the minimum Gmail scope per phase.
- **Never log email bodies, tokens or API keys.** Redact personal identifiers before text goes to an external LLM.
- When unsure whether mail matters, treat it as normal priority. Never silently ignore uncertain mail.
- Sender rules match the authenticated domain (DKIM/SPF), not the display name.
- Processing must be idempotent (no duplicate notifications or LLM calls). Never backfill old mail with the LLM.
- One failing account must not affect others (`active`, `needs_reconnect`, `blocked`; blocked copy is fixed in `DESIGN.md`).
- Everything that decides what is ignored or notified needs tests (rule engine, pipeline, fingerprinting, opportunity matching, search parsing, AI-off mode).
- Include a seed or demo mode with sample emails. Deployment must stay free. No paid services in the default setup.
- **Portability (owner's instruction):** the host (laptop now, Oracle later, e2-micro fallback) and the new-mail detection mode (`CHANGE_DETECTION=poll` default, `push` via Pub/Sub later) are chosen only in `.env`. Never hard-wire code to one host or one mode; both modes must go through `accounts.check_account()`. Keep README §6 (move to Oracle) and §7 (switch to push) working.

## 8. Stack defaults
Backend Python 3.12, FastAPI, SQLAlchemy + Alembic, Postgres, arq + Redis or the Postgres job queue. Processes: api, worker, scheduler. Android Kotlin, Jetpack Compose, FCM, Retrofit/OkHttp, Room. Web React + TypeScript (Vite). Gmail API with OAuth and Pub/Sub push. LLM provider interface, Gemini default. Docker Compose. Change only if the owner says so.

## 9. Repo map
| Path | What |
|---|---|
| `CLAUDE.md` | This guide |
| `PROGRESS.md` | Status, log, decisions, open questions |
| `DESIGN.md` | Design system |
| `Inbox_Agent_Master_Prompt.md` | Product spec and phases |
| `web/` | React + TypeScript web app (Vite): `src/api.ts` client, `src/offline.ts` + `public/sw.js` (opens while the server is off), `src/pages/` (`Ask.tsx` = Ask Sift) |
| `design/` | Static HTML prototypes: `landing/`, `web/`, `mobile/`, `shared/` (tokens, components, fonts) |
| `README.md` | Setup from scratch, acceptance checks, operations |
| `backend/` | FastAPI API (`app/api/`), worker (`app/worker.py`, `app/jobs.py`), scheduler (`app/scheduler.py`), accounts and change detection (`app/accounts.py`), mail provider + Gmail + OAuth + parsing (`app/mail/`), pipeline (`app/pipeline.py`), reader (`app/reader.py`, signed links `app/signing.py`), writing mail (`app/compose.py` MIME + reply/forward, `app/outbox.py` undo/send later/follow-ups, `app/api/compose.py`), AI on folders (`app/folder_ai.py`: AI filing, auto-sort, AI tasks), starter setup and reset (`app/starter.py`), Ask Sift / Sift AI (`app/assistant.py`: one AI call plans steps over the app's own actions; `app/api/assistant.py`), places (`app/places.py`: custom groups and folders with criteria, new mail routed to every place it fits), search (`app/search/`: query parser, engine, local matcher, semantic index, saved-search alerts), rules/heuristics/fingerprints, LLM layer (`app/llm/`), notifications (`app/notify.py`), sign-in (`app/security.py`), demo (`app/demo.py`), models (`app/models.py`), Alembic (`migrations/`), tests (`tests/`) |
| `android/` | Kotlin + Compose app, package `com.solarquack.sift`: `data/` (Retrofit API, session, push, `Offline.kt` saved copies while the server is off), `ui/theme` (DESIGN.md tokens, bundled fonts), `ui/screens`, `SiftMessagingService` |
| `docker-compose.yml`, `deploy/`, `scripts/` | Deployment (profiles: redis, tunnel, https), Caddy, `run-local.ps1` (native Windows), backup/restore |

Add new top-level folders to this table when they are created.

## 9a. Running and testing locally
See "Dev environment notes" at the bottom of `PROGRESS.md` (throwaway Postgres on port 5433, test command, Gradle loopback workaround). Every phase must end with the full test suite passing and, where possible, a real end-to-end run.

## 10. End of every session
1. All work committed (`git status` clean), nothing pushed.
2. `PROGRESS.md` log, status and open questions are current.
3. `DESIGN.md` / `README.md` match reality.
4. Tell the owner what changed, what is verified, what is not, and what you need from them next.

---

## 11. Production Environment & Deployment (LIVE on Oracle Cloud)

> [!IMPORTANT]
> **Production Server Details:**
> - **Host IP:** `130.210.19.66`
> - **SSH User:** `opc`
> - **SSH Key Location (on Owner's Laptop):** `C:\Users\solarquack\.ssh\oracle-sift.key` (also copied as `oracle_sift.key`)
> - **Quick SSH Command:** `ssh -i C:\Users\solarquack\.ssh\oracle-sift.key opc@130.210.19.66`
> - **Server Architecture & OS:** Ampere A1 (ARM64), 1 OCPU, 6 GB RAM, Oracle Linux 9.8
> - **Production Directory:** `/opt/sift`
> - **Public URL:** `https://sift.solarquack.in` (routed via Cloudflare Tunnel)

### Production Architecture
- **Container Stack (`/opt/sift/docker-compose.yml`):**
  - `sift-api`: FastAPI backend on `127.0.0.1:8000` (serving built web UI at `/app`)
  - `sift-worker`: arq Redis worker (`python -m app.worker`)
  - `sift-scheduler`: APScheduler polling Gmail every 5s (`python -m app.scheduler`)
  - `sift-postgres`: PostgreSQL 17 on `postgres:5432` (`pgdata` volume)
  - `sift-redis`: Redis 7 on `redis:6379` (`redisdata` volume)
- **Cloudflare Tunnel (`cloudflared.service`):** Runs natively on the Oracle VM host, forwarding public traffic from `sift.solarquack.in` directly to `http://localhost:8000`.
- **Anti-Reclamation Guard (`neveridle.service`):** Runs `/usr/local/bin/neveridle -cp 0.22 -m 1` at `nice 19`. Pins ~1.6 GiB total system memory (29%) and 22% CPU so Oracle never reclaims the instance under its 7-day idle policy.
- **Autostart Services:** `sift.service` (Docker Compose), `cloudflared.service`, `neveridle.service`, and `docker.service` are all systemd `enabled` on boot.
- **Automated Backups:** Daily crontab at 03:30 UTC (`30 3 * * * cd /opt/sift && ./scripts/backup.sh >> /opt/sift/backups/backup.log 2>&1`) writing timestamped `sift-*.sql.gz` to `/opt/sift/backups/`.

### How to Deploy Changes to Production (Standard Workflow)
1. Write and test code locally on the laptop.
2. Commit changes: `git add . && git commit -m "Your commit message"`
3. Push to GitHub: `git push origin main` *(or have the owner push)*
4. SSH into the Oracle VM:
   ```bash
   ssh -i C:\Users\solarquack\.ssh\oracle-sift.key opc@130.210.19.66
   ```
5. Pull and rebuild production:
   ```bash
   cd /opt/sift && git pull && docker compose up -d --build
   ```
   *(Alembic migrations run automatically on container startup; Postgres/Redis data is fully preserved).*
6. If only `/opt/sift/.env` was modified:
   ```bash
   cd /opt/sift && docker compose up -d
   ```
7. Verify deployment:
   ```bash
   curl -s http://127.0.0.1:8000/health
   # or from any browser/device: https://sift.solarquack.in/health
   ```

### Disaster Recovery / Emergency Failover Back to Laptop
If Oracle Cloud is down or undergoing maintenance, Sift can resume on the owner's laptop in under 60 seconds:
1. In Administrator PowerShell on laptop:
   ```powershell
   Start-Service Cloudflared
   powershell -ExecutionPolicy Bypass -File D:\inbox-app\scripts\sift.ps1 restore backups\sift-latest.dump
   powershell -ExecutionPolicy Bypass -File D:\inbox-app\scripts\sift.ps1 start
   ```
2. Cloudflare Tunnel reconnects to the laptop, and Sift catches up on Gmail history without losing any data.
