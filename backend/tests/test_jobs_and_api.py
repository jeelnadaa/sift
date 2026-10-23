from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app import crypto, fcm, jobs
from app.models import Device, Job, User

ADMIN = {"X-Admin-Token": "test-admin-token"}


# ---- postgres queue ----------------------------------------------------------

def test_worker_runs_queued_job(db):
    jobs.enqueue_pg(db, "gmail_push", {"email": "nobody@x.com", "history_id": 1, "pubsub_message_id": "a"})
    db.commit()
    assert jobs.run_one(db) is True
    assert db.scalar(select(Job.status)) == "done"
    assert jobs.run_one(db) is False  # queue empty


def test_failed_job_is_retried_with_backoff_then_marked_failed(db, monkeypatch):
    def boom(payload):
        raise RuntimeError("nope")
    monkeypatch.setitem(jobs.HANDLERS, "boom", boom)
    jobs.enqueue_pg(db, "boom", {})
    db.commit()
    jobs.run_one(db)
    job = db.scalar(select(Job))
    db.refresh(job)
    assert job.status == "queued" and job.attempts == 1 and job.run_at > datetime.now(UTC)
    assert "RuntimeError" in job.last_error

    job.attempts, job.run_at = jobs.MAX_ATTEMPTS - 1, datetime.now(UTC)
    db.commit()
    jobs.run_one(db)
    db.refresh(job)
    assert job.status == "failed"


# ---- crypto ------------------------------------------------------------------

def test_encrypt_roundtrip_and_key_rotation(override_settings):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    crypto._fernet.cache_clear()
    override_settings(encryption_keys=old)
    token = crypto.encrypt("refresh-token")
    assert token != "refresh-token" and crypto.decrypt(token) == "refresh-token"

    crypto._fernet.cache_clear()
    override_settings(encryption_keys=f"{new},{old}")
    assert crypto.decrypt(token) == "refresh-token"  # old ciphertext still readable
    crypto._fernet.cache_clear()


def test_encrypt_without_keys_fails_loudly(override_settings):
    crypto._fernet.cache_clear()
    override_settings(encryption_keys="")
    with pytest.raises(crypto.EncryptionNotConfigured):
        crypto.encrypt("x")


# ---- API ---------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "queue": "postgres", "database": "ok"}


def test_device_registration_requires_admin_and_upserts(client, db):
    db.add(User(email="me@gmail.com"))
    db.commit()
    payload = {"user_email": "me@gmail.com", "fcm_token": "token-1234567890", "label": "Pixel"}
    assert client.post("/api/v1/devices", json=payload).status_code == 401
    assert client.post("/api/v1/devices", json=payload, headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.post("/api/v1/devices", json=payload, headers=ADMIN).status_code == 201
    assert client.post("/api/v1/devices", json={**payload, "label": "Pixel 9"}, headers=ADMIN).status_code == 201
    assert list(db.scalars(select(Device.label))) == ["Pixel 9"]


def test_test_push_sends_and_prunes_unregistered_tokens(client, db, monkeypatch):
    user = User(email="me@gmail.com")
    db.add(user)
    db.flush()
    db.add_all([Device(user_id=user.id, fcm_token="good-token-xyz"), Device(user_id=user.id, fcm_token="dead-token-xyz")])
    db.commit()
    sent = []

    def fake_send(token, data):
        sent.append(data)
        return fcm.SendResult(ok=True) if token.startswith("good") else fcm.SendResult(ok=False, token_invalid=True, error="UNREGISTERED")
    monkeypatch.setattr(fcm, "send", fake_send)

    r = client.post("/api/v1/dev/test-push", json={}, headers=ADMIN)
    assert r.json() == {"sent": 1, "failed": ["UNREGISTERED"], "removed_invalid": 1}
    assert sent[0]["type"] == "test" and sent[0]["priority"] == "urgent"
    assert list(db.scalars(select(Device.fcm_token))) == ["good-token-xyz"]


def test_test_push_reports_missing_fcm_config(client, override_settings):
    fcm._credentials.cache_clear()
    override_settings(firebase_credentials_file="", firebase_project_id="")
    r = client.post("/api/v1/dev/test-push", json={"token": "abc"}, headers=ADMIN)
    assert r.status_code == 503
