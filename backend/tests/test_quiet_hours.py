"""Tests for Quiet Hours and Notification Filtering (Phase B Item 4)."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app import notify, user_settings
from app.models import Rule, User
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


def test_settings_quiet_hours_and_category_validation(client, db):
    user = User(email="demo@demo.sift.local")
    db.add(user)
    db.commit()
    headers = H(user)

    # Valid settings
    res = client.patch("/api/v1/settings", headers=headers, json={
        "quiet_hours_enabled": True,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "08:30",
        "muted_categories": ["fyi", "promotions"],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["quiet_hours_enabled"] is True
    assert data["quiet_hours_start"] == "23:00"
    assert data["quiet_hours_end"] == "08:30"
    assert data["muted_categories"] == ["fyi", "promotions"]

    # Invalid start time
    assert client.patch("/api/v1/settings", headers=headers, json={"quiet_hours_start": "25:00"}).status_code == 422
    assert client.patch("/api/v1/settings", headers=headers, json={"quiet_hours_start": "invalid"}).status_code == 422

    # Invalid muted_categories
    assert client.patch("/api/v1/settings", headers=headers, json={"muted_categories": "not a list"}).status_code == 422
    assert client.patch("/api/v1/settings", headers=headers, json={"muted_categories": [123]}).status_code == 422


def test_is_in_quiet_hours_logic():
    # 1. Disabled returns False
    s = {"quiet_hours_enabled": False, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "timezone": "Asia/Kolkata"}
    assert not user_settings.is_in_quiet_hours(s)

    # 2. Overnight window: 22:00 to 07:00 IST (UTC+5:30)
    s["quiet_hours_enabled"] = True

    # 23:30 IST is 18:00 UTC
    dt_inside_1 = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    assert user_settings.is_in_quiet_hours(s, now_utc=dt_inside_1)

    # 06:30 IST is 01:00 UTC
    dt_inside_2 = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)
    assert user_settings.is_in_quiet_hours(s, now_utc=dt_inside_2)

    # 12:00 IST is 06:30 UTC -> outside
    dt_outside = datetime(2026, 10, 26, 6, 30, tzinfo=UTC)
    assert not user_settings.is_in_quiet_hours(s, now_utc=dt_outside)

    # Boundary: exactly 07:00 IST (01:30 UTC) -> quiet hours ended
    dt_end_exact = datetime(2026, 10, 26, 1, 30, tzinfo=UTC)
    assert not user_settings.is_in_quiet_hours(s, now_utc=dt_end_exact)

    # 3. Same-day window: 13:00 to 14:00 IST
    s_day = {"quiet_hours_enabled": True, "quiet_hours_start": "13:00", "quiet_hours_end": "14:00", "timezone": "Asia/Kolkata"}
    # 13:30 IST is 08:00 UTC
    assert user_settings.is_in_quiet_hours(s_day, now_utc=datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    # 14:30 IST is 09:00 UTC
    assert not user_settings.is_in_quiet_hours(s_day, now_utc=datetime(2026, 10, 26, 9, 0, tzinfo=UTC))


def test_quiet_hours_silences_normal_mail_but_never_urgent(db, setup, fcm_sends, monkeypatch):
    user, account, provider, msgs = setup
    # Make sure urgent rule exists for fraud alerts
    db.add(Rule(user_id=user.id, position=-1, name="fraud urgent", origin="editor",
                conditions={"field": "subject", "op": "contains_any", "value": ["card blocked"]}, action={"type": "notify_urgent"}))
    db.commit()

    # Enable quiet hours: 22:00 to 07:00 IST
    user_settings.update(db, user.id, {
        "quiet_hours_enabled": True,
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "timezone": "Asia/Kolkata",
    })

    # Mock datetime.now to be inside quiet hours (23:30 IST = 18:00 UTC)
    inside_utc = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)

    real_is_in_quiet = user_settings.is_in_quiet_hours
    monkeypatch.setattr(user_settings, "is_in_quiet_hours", lambda s, now_utc=None: real_is_in_quiet(s, now_utc or inside_utc))

    # Recruiter mail arrives (normal priority) -> suppressed by quiet hours
    out_recruiter = run(db, account, provider, msgs["recruiter"])
    assert not out_recruiter.notified
    assert fcm_sends == []

    # Fraud mail arrives (urgent priority) -> urgent breaks through quiet hours!
    out_fraud = run(db, account, provider, msgs["fraud"])
    assert out_fraud.priority == "urgent" and out_fraud.notified
    assert len(fcm_sends) == 1
    assert fcm_sends[0]["priority"] == "urgent"


def test_muted_categories_silences_normal_mail_but_never_urgent(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)
    # Add urgent rule for fraud alerts
    db.add(Rule(user_id=user.id, position=-1, name="fraud urgent", origin="editor",
                conditions={"field": "subject", "op": "contains_any", "value": ["card blocked"]}, action={"type": "notify_urgent"}))
    db.commit()

    # Recruiter mail has category "recruiter". Mute "recruiter" category
    user_settings.update(db, user.id, {
        "quiet_hours_enabled": False,
        "muted_categories": ["recruiter"],
    })

    # Normal recruiter mail is suppressed because its category is muted
    out_recruiter = run(db, account, provider, msgs["recruiter"])
    assert not out_recruiter.notified
    assert fcm_sends == []

    # Fraud mail arrives as urgent -> urgent breaks through category mute!
    out_fraud = run(db, account, provider, msgs["fraud"])
    assert out_fraud.priority == "urgent" and out_fraud.notified
    assert len(fcm_sends) == 1
    assert fcm_sends[0]["priority"] == "urgent"
