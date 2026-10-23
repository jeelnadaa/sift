# Sift

Personal email assistant: watches your Gmail accounts, runs your rules first, uses a small LLM (your own key) only for what rules don't settle, and pushes priority mail to your Android phone in seconds. Full spec: [`Inbox_Agent_Master_Prompt.md`](Inbox_Agent_Master_Prompt.md). Status: [`PROGRESS.md`](PROGRESS.md). Design: [`DESIGN.md`](DESIGN.md).

**Current phase: 0 (setup).** The backend receives authenticated Gmail Pub/Sub pushes and queues them; it can send a test FCM push to the Android app. Gmail account connection and the processing pipeline arrive in Phase 1.

```
Gmail ─► Cloud Pub/Sub ─► Caddy (HTTPS) ─► api /webhooks/gmail ─► queue (Redis or Postgres) ─► worker ─► Postgres
                                                                                                   └──► FCM ─► Android app
```

## Repository layout

| Path | What |
|---|---|
| `backend/` | FastAPI API, worker, SQLAlchemy models, Alembic migrations, tests |
| `android/` | Kotlin + Compose app (Phase 0: FCM token, channels, battery exemption) |
| `design/` | HTML design prototypes (landing, web UI, mobile) |
| `deploy/Caddyfile` | HTTPS reverse proxy |
| `scripts/` | `backup.sh`, `restore.sh` |
| `docker-compose.yml` | postgres, redis, api, worker, caddy |

---

## 1. Google Cloud project (Gmail API, Pub/Sub)

Use one Google Cloud project for everything, and attach Firebase to the same project (step 2). Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install) or use Cloud Shell.

```bash
PROJECT=your-project-id
DOMAIN=sift.solarquack.in
gcloud config set project $PROJECT
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')

# APIs
gcloud services enable gmail.googleapis.com pubsub.googleapis.com fcm.googleapis.com

# Topic that Gmail publishes to, and permission for Gmail's push service account to publish
gcloud pubsub topics create sift-gmail
gcloud pubsub topics add-iam-policy-binding sift-gmail \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com --role=roles/pubsub.publisher

# Service account whose OIDC token signs every push; Pub/Sub's agent must be able to mint tokens for it
gcloud iam service-accounts create sift-pubsub-push --display-name="Sift Pub/Sub push"
gcloud projects add-iam-policy-binding $PROJECT \
  --member=serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/iam.serviceAccountTokenCreator

# Push subscription to the webhook (create it once the server answers on HTTPS, step 4)
gcloud pubsub subscriptions create sift-gmail-push --topic=sift-gmail \
  --push-endpoint=https://$DOMAIN/webhooks/gmail \
  --push-auth-service-account=sift-pubsub-push@$PROJECT.iam.gserviceaccount.com \
  --push-auth-token-audience=https://$DOMAIN/webhooks/gmail \
  --ack-deadline=20
```

Put these values in `.env`: `GOOGLE_PROJECT_ID`, `PUBSUB_TOPIC=projects/$PROJECT/topics/sift-gmail`, `PUBSUB_AUDIENCE=https://$DOMAIN/webhooks/gmail`, `PUBSUB_SERVICE_ACCOUNT=sift-pubsub-push@$PROJECT.iam.gserviceaccount.com`.

If your organization enforces domain-restricted sharing, the `gmail-api-push` binding can be blocked; a personal Google account avoids this.

### OAuth consent screen (needed for Phase 1, set it up now)

Console → APIs & Services → OAuth consent screen:
1. User type **External**, publishing status **Testing**. Add every Gmail address you will connect as a **test user**.
2. Scope: `https://www.googleapis.com/auth/gmail.readonly` only. Broader scopes are requested in phases 3 and 4.
3. Credentials → Create credentials → OAuth client ID → **Web application**, redirect URI `https://$DOMAIN/api/v1/accounts/oauth/callback` (used from Phase 1).

**Testing-mode limit:** refresh tokens issued to apps in Testing status expire after about 7 days. Sift marks such accounts `needs_reconnect` and shows a Reconnect banner. Options: reconnect weekly, or submit the app for verification (the read-only Gmail scope is a restricted scope and verification requires a security assessment, which is impractical for a personal app). College or work Workspace accounts may be blocked by their administrator; Sift shows them as `blocked`.

## 2. Firebase (push notifications)

1. [Firebase console](https://console.firebase.google.com) → Add project → choose the **same** Google Cloud project.
2. Add an Android app with package name `com.solarquack.sift`. Download `google-services.json` into `android/app/` (it is git-ignored).
3. Project settings → Service accounts → **Generate new private key**. Save it as `secrets/firebase.json` (git-ignored). Set `FIREBASE_PROJECT_ID` in `.env`.

## 3. Android app

Requirements: Android Studio (or the Android SDK with platform 35) and JDK 17+.

```bash
cd android
./gradlew assembleDebug        # Windows: gradlew.bat assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Open the app, grant notifications, tap **Fix** on battery optimization, and copy the FCM token.

Without `google-services.json` the app still builds but shows "Firebase not configured".

> Windows note: if Gradle fails with `Unable to establish loopback connection`, set `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:\gtmp` (any short existing folder) and retry.

## 4. Server (Oracle Cloud Always Free)

Check Oracle's current Always Free limits before creating anything; they change.

1. Create a VM in your home region (Mumbai or Hyderabad): shape **VM.Standard.A1.Flex**, at most **2 OCPU / 12 GB**, Ubuntu 24.04 (Arm). Keep a reserved public IP.
2. Networking: in the subnet's security list allow ingress TCP 80 and 443. Oracle's Ubuntu images also block them in iptables:
   ```bash
   sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save
   ```
3. DNS: add an `A` record `sift.solarquack.in → <VM public IP>`.
4. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER && newgrp docker
   ```
5. Deploy:
   ```bash
   sudo mkdir -p /opt/sift && sudo chown $USER /opt/sift && cd /opt/sift
   git clone https://github.com/jeelnadaa/sift.git . 
   cp .env.example .env && nano .env          # see "Environment" below
   # copy secrets/firebase.json from your machine: scp secrets/firebase.json vm:/opt/sift/secrets/
   docker compose up -d --build
   docker compose ps && curl -s https://sift.solarquack.in/health
   ```
6. Create the owner account: `docker compose exec api python -m app.cli create-user you@gmail.com`
7. Now create the Pub/Sub push subscription (last command in step 1).

### Environment

Copy `.env.example` to `.env`. Required for Phase 0 on the server:

| Variable | Value |
|---|---|
| `ENV` | `prod` |
| `COMPOSE_PROFILES` / `QUEUE_BACKEND` | `redis,https` / `redis` (Oracle) |
| `SIFT_DOMAIN`, `PUBLIC_BASE_URL` | your subdomain |
| `POSTGRES_PASSWORD` | long random string |
| `ENCRYPTION_KEYS` | output of `python -m app.cli gen-key` (or `docker compose run --rm api python -m app.cli gen-key`) |
| `ADMIN_TOKEN` | long random string (`openssl rand -hex 32`) |
| `PUBSUB_*`, `GOOGLE_PROJECT_ID` | from step 1 |
| `FIREBASE_PROJECT_ID` | from step 2 |

### Fallback host: Google Cloud e2-micro (1 GB RAM)

Same steps on an e2-micro Always Free VM (us-west1, us-central1 or us-east1), with `COMPOSE_PROFILES=https`, `QUEUE_BACKEND=postgres` and `PG_SHARED_BUFFERS=64MB`. Redis is not started; the worker polls the `jobs` table instead. Add 1 GB of swap.

## 5. Phase 0 acceptance checks

**A. A Pub/Sub push reaches the webhook.** Publish a Gmail-shaped message; Pub/Sub delivers it to the webhook with an OIDC token:

```bash
gcloud pubsub topics publish sift-gmail --message='{"emailAddress":"you@gmail.com","historyId":1}'
docker compose logs api worker | grep -i pubsub
# api:    pubsub push accepted (history 1)
# worker: pubsub push for unknown account (history 1)     <- expected until Phase 1 connects accounts
```

A request without a valid token is rejected: `curl -i -X POST https://$DOMAIN/webhooks/gmail -d '{}'` returns 401.

**B. A test FCM push reaches the phone.**

```bash
curl -X POST https://$DOMAIN/api/v1/dev/test-push \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"token":"<FCM token from the app>"}'
# {"sent":1,"failed":[],"removed_invalid":0}
```

The phone shows an urgent "Sift test push" notification, and the app shows the server-to-phone delay. Optionally register the device so later pushes need no token: `POST /api/v1/devices` with `{"user_email":"you@gmail.com","fcm_token":"..."}` and the same header.

## 6. Local development

Requirements: Python 3.12+, a Postgres you can create databases in. Docker is optional locally.

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
export DATABASE_URL=postgresql+psycopg://sift:pw@localhost:5432/sift QUEUE_BACKEND=postgres PUBSUB_VERIFY=false ADMIN_TOKEN=dev
alembic upgrade head
uvicorn app.main:app --reload          # terminal 1
python -m app.worker                   # terminal 2
python -m app.cli create-user you@gmail.com
python -m app.cli fake-push you@gmail.com 123   # simulated Pub/Sub push
```

Tests (they wipe the database you point them at):

```bash
TEST_DATABASE_URL=postgresql+psycopg://sift:pw@localhost:5432/sift_test python -m pytest -q
```

Design prototypes: `cd design && python -m http.server 8765`, then open `http://localhost:8765/web/`.

## 7. Operations

- **Backups:** `scripts/backup.sh` writes `backups/sift-<time>.sql.gz` and, if `BACKUP_RCLONE_REMOTE` is set (install and configure [rclone](https://rclone.org) for e.g. Google Drive), copies it off the VM. Cron: `30 3 * * * cd /opt/sift && ./scripts/backup.sh >> backups/backup.log 2>&1`. Restore: `scripts/restore.sh backups/<file>.sql.gz`.
- **Rebuild from scratch:** new VM → steps 4.1–4.5 → `scripts/restore.sh <latest backup>` → `docker compose up -d`. Pub/Sub keeps retrying undelivered pushes for up to 7 days, and Phase 1 catches up from each account's stored historyId, so no mail is lost.
- **Oracle reclaim risk:** Oracle may reclaim Always Free instances that stay idle (very low CPU, network and memory use over 7 days). A running Sift is rarely idle, but keep backups off the VM and follow the rebuild steps if the instance disappears. Upgrading the account to Pay-As-You-Go (still free within limits) removes idle reclamation.
- **Cost safety:** set a billing budget alert at ₹1 / $1 in both Google Cloud (Billing → Budgets & alerts) and Oracle (Billing → Budgets). Check usage in Google Cloud Billing → Reports and Oracle Cost Analysis. Pub/Sub, Gmail API and FCM usage for one person is far below the free tiers.
- **Logs:** `docker compose logs -f api worker`. Logs never contain email bodies, tokens or API keys.

## Known limitations (Phase 0)

- The Redis queue mode and the Docker Compose stack were written but not run on this machine (no Docker locally); the Postgres queue mode and the API were tested end to end. First server deploy is the real check.
- `/api/v1/devices` and `/api/v1/dev/*` use a shared admin token; per-user JWT auth arrives in Phase 1.
- The Android app is a setup screen only (token, permissions, battery exemption, channels). Feed and other screens arrive in Phase 1; it does not yet use the Satoshi and Clash Display fonts.
- Gmail watch, OAuth connect and the processing pipeline are Phase 1.
