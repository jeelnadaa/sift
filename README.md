# Sift

Personal email assistant: watches your Gmail accounts, runs your rules first, uses a small LLM (your own key) only for what rules don't settle, and pushes priority mail to your Android phone in seconds. Full spec: [`Inbox_Agent_Master_Prompt.md`](Inbox_Agent_Master_Prompt.md). Status: [`PROGRESS.md`](PROGRESS.md). Design: [`DESIGN.md`](DESIGN.md).

**Current phase: 1 (instant notification pipeline).** New mail on any connected Gmail account runs through your rules, free heuristics and, only if you added your own key, a small LLM, then notifies your phone by priority (urgent, normal, digest). Bank noise can be silenced without ever spending tokens. See section 5A for the app.

```
                 ┌── poll (default): scheduler asks Gmail "what changed?" every 10 s ──┐
Gmail ───────────┤                                                                      ├─► queue ─► worker ─► Postgres
                 └── push (optional): Gmail watch ─► Pub/Sub ─► /webhooks/gmail ───────┘              └──► FCM ─► phone
```

Two independent choices, both set in `.env`, no code changes:

| Choice | Options |
|---|---|
| **Where it runs** | Your laptop (native Windows or Docker Desktop), optionally exposed with Cloudflare Tunnel · Oracle Always Free VM · Google e2-micro |
| **How new mail is detected** (`CHANGE_DETECTION`) | `poll` (default: free, no Pub/Sub, no billing, ~5–10 s) · `push` (Pub/Sub, ~1–3 s, needs a billed Google Cloud project and public HTTPS) |

## Repository layout

| Path | What |
|---|---|
| `backend/` | FastAPI API, worker, scheduler, Gmail client, models, Alembic migrations, tests |
| `android/` | Kotlin + Compose app (Phase 0: FCM token, priority channels, battery exemption) |
| `design/` | HTML design prototypes (landing, web UI, mobile) |
| `docker-compose.yml` | postgres, redis, api, worker, scheduler, cloudflared, caddy |
| `deploy/Caddyfile` | HTTPS reverse proxy for a VM |
| `scripts/` | `run-local.ps1` (native Windows), `backup.sh`, `restore.sh` |

---

## 1. Google Cloud: Gmail API and OAuth client (free, no billing)

1. Open [console.cloud.google.com](https://console.cloud.google.com), create a project (e.g. `sift`). No billing account is needed.
2. APIs & Services → Library → enable **Gmail API**.
3. APIs & Services → **OAuth consent screen** (Google Auth Platform):
   - User type **External**, publishing status **Testing**.
   - Data access / scopes: add `https://www.googleapis.com/auth/gmail.readonly` only.
   - Audience → **Test users**: add every Gmail address you will connect.
4. APIs & Services → Credentials → Create credentials → **OAuth client ID** → **Web application**. Authorized redirect URIs:
   - `http://localhost:8000/api/v1/accounts/oauth/callback` (laptop)
   - later also `https://sift.solarquack.in/api/v1/accounts/oauth/callback` (tunnel or VM). You can keep both.
5. Copy the client ID and secret into `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

**Testing-mode limit:** refresh tokens issued to apps in Testing status expire after about 7 days. Sift marks the account `needs_reconnect`; reconnect it with the same link (step 5.1) and nothing is missed, because Sift resumes from where it stopped. Verification would remove the limit, but `gmail.readonly` is a restricted scope that needs a paid security assessment, which is impractical for a personal app.

**Blocked accounts:** college or work Workspace accounts may be blocked by their administrator. Google shows `admin_policy_enforced` on its own page and does not return to Sift, so the account is simply not connected. If a connected account gets blocked later, Sift marks it `blocked` when its token stops working.

## 2. Firebase (push notifications, free Spark plan)

1. [Firebase console](https://console.firebase.google.com) → Add project. It can be the same Google Cloud project as step 1 or a separate one; Sift only needs its project ID and the two files below. Stay on the free Spark plan.
2. Add an Android app, package name `com.solarquack.sift`. Download `google-services.json` into `android/app/` (git-ignored).
3. Project settings → Service accounts → **Generate new private key**. Save as `secrets/firebase.json` (git-ignored). Set `FIREBASE_PROJECT_ID` in `.env`.

## 3. Android app

Requirements: Android Studio (or Android SDK platform 35) and JDK 17+.

```bash
cd android
./gradlew assembleDebug        # Windows: gradlew.bat assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Open the app, grant notifications, tap **Fix** on battery optimization, and copy the FCM token. Without `google-services.json` the app builds but shows "Firebase not configured".

> Windows: if Gradle fails with `Unable to establish loopback connection`, set `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:\gtmp` (any short existing folder) and retry.

## 4. Run on your laptop

Start from the template: `cp .env.example .env` (Windows: `copy .env.example .env`) and fill in:

| Variable | Laptop value |
|---|---|
| `CHANGE_DETECTION` | `poll` |
| `PUBLIC_BASE_URL` | `http://localhost:8000` (or your tunnel URL, step 4C) |
| `APP_SECRET`, `ADMIN_TOKEN` | long random strings (`openssl rand -hex 32`, or `python -c "import secrets;print(secrets.token_hex(32))"`) |
| `ENCRYPTION_KEYS` | `python -m app.cli gen-key`. **Back this up**: without it stored tokens cannot be read and every account must reconnect |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | step 1 |
| `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_FILE` | step 2 (`./secrets/firebase.json`; for the native run use the absolute path) |

### 4A. Native Windows (no Docker)

Uses the Postgres you already have and the Postgres job queue (no Redis).

```powershell
# one-time: database and user (enter your postgres superuser password when asked)
psql -U postgres -c "CREATE USER sift WITH PASSWORD 'pick-a-password';" -c "CREATE DATABASE sift OWNER sift;"

# one-time: Python environment (Python 3.12+)
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd ..
```

In `.env` also set `QUEUE_BACKEND=postgres` and `DATABASE_URL=postgresql+psycopg://sift:pick-a-password@localhost:5432/sift`. Then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1     # API + worker + scheduler; logs in .\logs

# second window, once:
cd backend
.venv\Scripts\python -m app.cli create-user you@gmail.com
```

### 4B. Docker Desktop

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (free for personal use). In `.env`: `COMPOSE_PROFILES=redis` (add `,tunnel` for 4C), `QUEUE_BACKEND=redis`, `POSTGRES_PASSWORD=...`. Then:

```bash
docker compose up -d --build
docker compose exec api python -m app.cli create-user you@gmail.com
```

### 4C. Public HTTPS with Cloudflare Tunnel (how sift.solarquack.in is set up)

A tunnel only works for a domain whose DNS Cloudflare manages. GoDaddy stays the registrar and Vercel keeps hosting the portfolio; Cloudflare only answers DNS.

1. **Cloudflare DNS (free):** dash.cloudflare.com → Add a domain → `solarquack.in` → Free. Keep exactly the existing records and set the Vercel ones to **DNS only (grey cloud)**, otherwise Vercel's certificates and redirects break:
   `A @ 216.198.79.1` (Vercel), `CNAME www → solarquack.in`, `TXT @ google-site-verification=…`, `TXT _dmarc …`. Delete GoDaddy's `_domainconnect` CNAME.
2. **Check before switching:** query Cloudflare's assigned nameservers directly (e.g. `nslookup solarquack.in keyla.ns.cloudflare.com`) and compare with what GoDaddy serves.
3. **Switch:** GoDaddy → domain → DNS → Nameservers → "I'll use my own" → the two Cloudflare nameservers. Propagation to the `.in` registry took about an hour; the site stays up because both sides serve the same records. Undo by restoring `ns11/ns12.domaincontrol.com`.
4. **Vercel:** add `www.solarquack.in` to the project as a redirect to `solarquack.in` so `www` gets a certificate.
5. **Tunnel:** Zero Trust (Free) → Networks → Tunnels → Create → Cloudflared → `sift-laptop`. On the laptop (admin PowerShell): `winget install --id Cloudflare.cloudflared`, then the `cloudflared.exe service install <token>` command shown (runs as a Windows service). Public hostname: `sift` . `solarquack.in` → HTTP `localhost:8000`.
6. **Sift:** `PUBLIC_BASE_URL=https://sift.solarquack.in` in `.env`, add `https://sift.solarquack.in/api/v1/accounts/oauth/callback` to the OAuth client's redirect URIs, and run `run-local.ps1` **without** `-Lan` (the tunnel reaches localhost; nothing listens on Wi-Fi). The app signs in with `https://sift.solarquack.in` and works on mobile data.

With Docker instead of a Windows service: put the token in `TUNNEL_TOKEN`, add `tunnel` to `COMPOSE_PROFILES`, and route the hostname to `http://api:8000`.

Exposed to the internet, Sift keeps `/docs` off (`API_DOCS=false`), throttles failed sign-ins (`LOGIN_ATTEMPTS` per email and per visitor in 15 minutes), requires sign-in on every app endpoint, and verifies Google's signature on the Pub/Sub webhook.

**Laptop as a server:** set Windows to never sleep while plugged in (Settings → System → Power). While the laptop sleeps nothing is detected; on wake, Sift resumes from its saved position and processes everything that arrived (Gmail keeps about a week of history).

## 5. Phase 0 acceptance checks

**A. A connected account's new mail is detected within seconds.**

```bash
cd backend
python -m app.cli connect-url you@gmail.com     # open the printed link, sign in, allow read-only access
python -m app.cli accounts                      # you@gmail.com   active   history=...
```

Send yourself an email from another address. Within about 10 seconds the worker log shows:

```
INFO app.accounts: account <id>: 1 new message(s)
```

(native: `logs\worker.log`; Docker: `docker compose logs -f worker`). Only counts are logged, never subjects or bodies.

**B. A test FCM push reaches the phone.**

```bash
curl -X POST http://localhost:8000/api/v1/dev/test-push \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"token":"<FCM token from the app>"}'
# {"sent":1,"failed":[],"removed_invalid":0}
```

The phone shows an urgent "Sift test push", and the app shows the server-to-phone delay. Register the device so later pushes need no token: `POST /api/v1/devices` with `{"user_email":"you@gmail.com","fcm_token":"..."}` and the same header.

## 5A. Using Sift (Phase 1)

1. **App password** (once): `cd backend` then `.venv\Scripts\python -m app.cli set-password you@gmail.com` (asks twice, never shown).
2. **Run so the phone can reach it:** `powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Lan`. It prints `Phone app server address: http://192.168.x.x:8000`. Allow Python on private networks if Windows asks.
3. **Install the app** (`android/app/build/outputs/apk/debug/app-debug.apk`) and sign in with that address, your email and the password. The app registers itself for notifications.
4. **Rules:** `python -m app.cli starter-rules you@gmail.com` adds "Bank transactions: silent (except fraud alerts)" (Kotak and Slice; edit the domains in `app/demo.py` or via the API). Rules are created through `POST /api/v1/rules`; the in-app editor comes in Phase 2. Rules match the authenticated sender domain, so spoofed mail never matches.
5. **AI (optional, your own key):** in the app, Settings → AI provider → paste a Gemini API key from [aistudio.google.com](https://aistudio.google.com) → Save and test. Without a valid key Sift makes no AI calls and delivers unhandled mail as normal priority. The daily token cap (default 50,000) is in settings.
6. **Demo:** `python -m app.cli demo you@gmail.com` runs five sample mails (placement drive, HirePro link, bank debit, fraud alert, recruiter) through the real pipeline and notifies your phone; `demo-clear` removes them.

What decides priority, in order: your rules (first match wins) → Gmail Promotions/Social tab → digest → a template you silenced before → the LLM (if your key is valid) → otherwise normal. Mail from a real person is never put in digest by the LLM, and anything that fails is delivered as normal, never hidden. Urgent notifications are re-sent every 5 minutes (up to 3 times) until the phone confirms it received them.

## 6. Move to Oracle Cloud later

Nothing in the code is tied to the laptop. To move:

1. On the laptop: back up the database (Docker: `scripts/backup.sh`; native: `pg_dump -U sift -d sift --no-owner | gzip > sift.sql.gz`). Keep your `.env`, especially `ENCRYPTION_KEYS`.
2. Create the VM (Check Oracle's current Always Free limits first): shape **VM.Standard.A1.Flex**, at most **2 OCPU / 12 GB**, Ubuntu 24.04 Arm, home region Mumbai or Hyderabad.
3. Networking: allow ingress TCP 80/443 in the subnet's security list, and in the VM `sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save`. DNS `A` record `sift.solarquack.in → VM IP` (or keep using Cloudflare Tunnel and skip ports and Caddy).
4. Install Docker: `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER && newgrp docker`.
5. Deploy:
   ```bash
   sudo mkdir -p /opt/sift && sudo chown $USER /opt/sift && cd /opt/sift
   git clone https://github.com/jeelnadaa/sift.git .
   # copy .env, secrets/firebase.json and the backup from the laptop (scp)
   # in .env: ENV=prod, COMPOSE_PROFILES=redis,https (or redis,tunnel), QUEUE_BACKEND=redis,
   #          PUBLIC_BASE_URL=https://sift.solarquack.in, POSTGRES_PASSWORD=...
   docker compose up -d --build postgres && ./scripts/restore.sh sift.sql.gz
   docker compose up -d --build
   curl -s https://sift.solarquack.in/health
   ```
6. Add `https://sift.solarquack.in/api/v1/accounts/oauth/callback` to the OAuth client. Stop Sift on the laptop.

Accounts continue from their saved positions, so mail that arrived during the move is still processed.

**Fallback host, Google e2-micro (1 GB RAM):** same steps with `COMPOSE_PROFILES=https`, `QUEUE_BACKEND=postgres`, `PG_SHARED_BUFFERS=64MB`, plus 1 GB swap. It needs a billing account, like Pub/Sub.

## 7. Optional: switch to Pub/Sub push

Use the **Google Cloud project that holds the Gmail API and OAuth client** (step 1), not a separate Firebase project: Gmail's watch only accepts a topic in the OAuth client's project. That project needs billing enabled (Pub/Sub stays within its free tier for one person) and Sift needs a stable public HTTPS URL (Cloudflare Tunnel with your own hostname, or a VM; not a random trycloudflare.com URL).

```bash
PROJECT=your-project-id; DOMAIN=sift.solarquack.in
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud services enable pubsub.googleapis.com
gcloud pubsub topics create sift-gmail
gcloud pubsub topics add-iam-policy-binding sift-gmail \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com --role=roles/pubsub.publisher
gcloud iam service-accounts create sift-pubsub-push
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com --role=roles/iam.serviceAccountTokenCreator
gcloud pubsub subscriptions create sift-gmail-push --topic=sift-gmail \
  --push-endpoint=https://$DOMAIN/webhooks/gmail \
  --push-auth-service-account=sift-pubsub-push@$PROJECT.iam.gserviceaccount.com \
  --push-auth-token-audience=https://$DOMAIN/webhooks/gmail --ack-deadline=20
```

In `.env`: `CHANGE_DETECTION=push`, `PUBSUB_TOPIC=projects/$PROJECT/topics/sift-gmail`, `PUBSUB_AUDIENCE=https://$DOMAIN/webhooks/gmail`, `PUBSUB_SERVICE_ACCOUNT=sift-pubsub-push@$PROJECT.iam.gserviceaccount.com`, `PUBSUB_VERIFY=true`. Restart. The scheduler starts a Gmail watch for every account within the hour (and renews daily), and keeps a safety check every 5 minutes. Test: `gcloud pubsub topics publish sift-gmail --message='{"emailAddress":"you@gmail.com","historyId":1}'` → `pubsub push accepted` in the API log. Switch back any time by setting `poll`.

## 8. Development and tests

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
TEST_DATABASE_URL=postgresql+psycopg://sift:pw@localhost:5432/sift_test python -m pytest -q   # wipes that database
python -m app.cli check          # run one check of every account now
python -m app.cli fake-push you@gmail.com 123   # simulated Pub/Sub push (PUBSUB_VERIFY=false)
```

Design prototypes: `cd design && python -m http.server 8765`, then open `http://localhost:8765/web/`.

## 9. Operations

- **Backups:** `scripts/backup.sh` (Docker hosts) writes `backups/sift-<time>.sql.gz` and copies it off the machine if `BACKUP_RCLONE_REMOTE` is set ([rclone](https://rclone.org), e.g. Google Drive). Cron: `30 3 * * * cd /opt/sift && ./scripts/backup.sh >> backups/backup.log 2>&1`. Restore: `scripts/restore.sh <file>`. Native Windows: `pg_dump` as in section 6, scheduled with Task Scheduler.
- **Rebuild from scratch:** new host → section 6 steps → restore the latest backup → start. Accounts resume from their saved positions (Gmail keeps about a week of history).
- **Oracle reclaim risk:** Oracle may reclaim Always Free instances that stay idle for 7 days. A running Sift is rarely idle, but keep backups off the VM. Upgrading the account to Pay-As-You-Go (still free within limits) removes idle reclamation.
- **Cost safety:** everything in the default setup is free (Gmail API, OAuth, FCM Spark plan, Cloudflare Tunnel free plan, Oracle Always Free). If you enable billing for Pub/Sub, set a budget alert of ₹100 in Google Cloud (Billing → Budgets & alerts), and on Oracle in Billing → Budgets. Check usage in Google Cloud Billing → Reports and Oracle Cost Analysis.
- **Logs** never contain email bodies, subjects, tokens or API keys.

## Known limitations (Phase 1)

- Verified on the owner's laptop (native Windows, Postgres queue, poll mode) with a real Gmail account, phone and Gemini key. Docker Compose, the Redis queue, Cloudflare Tunnel and push mode are written but not yet run.
- Poll mode: about 25 s from Gmail receiving a mail to the phone (≈17 s until it appears in Gmail's change history plus the 5 s poll, ≈7 s processing with AI, ≈1 s push). Push mode removes most of the first part.
- `sift.solarquack.in` is only up while the laptop is on (and awake) with Sift and the tunnel service running.
- If an account is offline for over a week, Gmail's history expires and Sift restarts from "now" without scanning the gap.
- When the daily token cap is reached, mail is delivered as normal straight away rather than queued for AI later. A rate-limited (429) AI call is retried once, then the mail is delivered as normal.
- Not yet: quiet hours, focus mode, rule editor with preview, plain-English rules, onboarding scan, opportunities, folders, grouping (Phase 2); HTML reader and search (Phase 3); offline cache in the app.
