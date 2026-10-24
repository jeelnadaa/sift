"""Settings loaded from environment variables (see ../.env.example).

Nothing secret has a default. Missing secrets fail loudly where they are used,
so the app still boots for local work without every integration configured.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"

    database_url: str = "postgresql+psycopg://sift:sift@localhost:5432/sift"

    # "redis" (default host, uses arq) or "postgres" (1 GB fallback host, no Redis).
    queue_backend: Literal["redis", "postgres"] = "redis"
    redis_url: str = "redis://localhost:6379/0"

    # Fernet keys, comma separated, newest first. Used for refresh tokens and LLM keys.
    encryption_keys: str = ""

    # Protects /api/v1/dev/* and device registration until JWT auth lands in Phase 1.
    admin_token: str = ""

    # Signs OAuth state (and JWTs from Phase 1). Long random string.
    app_secret: str = ""

    # How new mail is detected:
    #   poll: the scheduler asks Gmail for changes every POLL_INTERVAL_SECONDS (no billing, no public webhook)
    #   push: Gmail watch + Cloud Pub/Sub push to /webhooks/gmail (needs a billed GCP project and public HTTPS)
    change_detection: Literal["poll", "push"] = "poll"
    poll_interval_seconds: int = 5

    # Google OAuth client (Web application). Redirect URI = PUBLIC_BASE_URL + /api/v1/accounts/oauth/callback
    google_client_id: str = ""
    google_client_secret: str = ""

    # Pub/Sub push authentication (OIDC token on every push). Only used when CHANGE_DETECTION=push.
    pubsub_verify: bool = True
    pubsub_audience: str = ""
    pubsub_service_account: str = ""

    # App sign-in tokens (JWT, HS256 with APP_SECRET).
    jwt_days: int = 30

    # LLM: every user brings their own key. This only pre-fills the model field in Settings.
    llm_default_provider: str = "gemini"
    llm_default_model: str = "gemini-3.5-flash-lite"

    google_project_id: str = ""
    pubsub_topic: str = ""  # projects/<id>/topics/<name>

    # Firebase Cloud Messaging (HTTP v1).
    firebase_project_id: str = ""
    firebase_credentials_file: str = ""  # service account JSON with FCM send rights


@lru_cache
def get_settings() -> Settings:
    return Settings()


def setup_logging() -> None:
    import logging

    logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO; with polling that is a line every few seconds.
    logging.getLogger("httpx").setLevel(logging.WARNING)
