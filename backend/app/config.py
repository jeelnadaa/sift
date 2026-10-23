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

    # Pub/Sub push authentication (OIDC token on every push).
    pubsub_verify: bool = True
    pubsub_audience: str = ""
    pubsub_service_account: str = ""

    google_project_id: str = ""
    pubsub_topic: str = ""  # projects/<id>/topics/<name>

    # Firebase Cloud Messaging (HTTP v1).
    firebase_project_id: str = ""
    firebase_credentials_file: str = ""  # service account JSON with FCM send rights


@lru_cache
def get_settings() -> Settings:
    return Settings()
