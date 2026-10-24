"""Tests need a disposable Postgres database: set TEST_DATABASE_URL.
The schema is built with the real Alembic migrations, so migrations are tested too."""
import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.exit("Set TEST_DATABASE_URL to a disposable Postgres database (it will be wiped)", returncode=2)

os.environ.update(
    ENV="test",
    DATABASE_URL=TEST_DB,
    QUEUE_BACKEND="postgres",
    ADMIN_TOKEN="test-admin-token",
    ENCRYPTION_KEYS="",
    PUBSUB_VERIFY="false",
    PUBSUB_AUDIENCE="https://example.test/webhooks/gmail",
    PUBSUB_SERVICE_ACCOUNT="push@proj.iam.gserviceaccount.com",
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.models import Base  # noqa: E402

HERE = os.path.dirname(__file__)


@pytest.fixture(scope="session", autouse=True)
def schema():
    cfg = Config(os.path.join(HERE, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "..", "migrations"))
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    from app import throttle
    throttle._failures.clear()
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def override_settings(monkeypatch):
    """Change settings for one test: override_settings(pubsub_verify=True)."""
    def apply(**kw):
        s = get_settings()
        for k, v in kw.items():
            monkeypatch.setattr(s, k, v)
        return s
    return apply


@pytest.fixture
def keys(override_settings):
    """Encryption + signing keys for tests that store secrets or issue JWTs."""
    from cryptography.fernet import Fernet

    from app import crypto
    crypto._fernet.cache_clear()
    override_settings(encryption_keys=Fernet.generate_key().decode(), app_secret="test-app-secret")
    yield
    crypto._fernet.cache_clear()


@pytest.fixture
def fcm_sends(monkeypatch):
    """Captures FCM sends instead of calling Firebase."""
    from app import fcm
    sent = []

    def fake_send(token, data):
        sent.append({"token": token, **data})
        return fcm.SendResult(ok=True)
    monkeypatch.setattr(fcm, "send", fake_send)
    return sent
