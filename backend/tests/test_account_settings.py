"""Tests for per-account signatures and sender profiles."""
import uuid
import pytest
from app import user_settings
from app.models import GmailAccount, User
from app.security import create_token


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.fixture
def account_world(db):
    user = User(email="user@demo.sift.local")
    db.add(user)
    db.flush()
    acc = GmailAccount(
        user_id=user.id,
        email="work@demo.sift.local",
        status="active",
    )
    db.add(acc)
    db.commit()
    return user, acc


def test_per_account_settings_fallback_and_overrides(client, db, account_world):
    user, acc = account_world

    # Initially: default user settings
    client.patch("/api/v1/settings", headers=H(user), json={
        "sender_name": "Demo User",
        "signature": "Default Signature",
    })

    # Account with no overrides inherits user settings
    res = client.get(f"/api/v1/settings?account_id={acc.id}", headers=H(user)).json()
    assert res["sender_name"] == "Demo User"
    assert res["signature"] == "Default Signature"

    # Also available via /accounts/{id}/settings
    res2 = client.get(f"/api/v1/accounts/{acc.id}/settings", headers=H(user)).json()
    assert res2["sender_name"] == "Demo User"
    assert res2["signature"] == "Default Signature"

    # Set per-account overrides via PATCH /settings?account_id=...
    patched = client.patch(
        f"/api/v1/settings?account_id={acc.id}",
        headers=H(user),
        json={"sender_name": "Work Alias", "signature": "Work Signature\nAcme Corp"},
    ).json()
    assert patched["sender_name"] == "Work Alias"
    assert patched["signature"] == "Work Signature\nAcme Corp"

    # Account settings reflect the override
    acc_res = client.get(f"/api/v1/settings?account_id={acc.id}", headers=H(user)).json()
    assert acc_res["sender_name"] == "Work Alias"
    assert acc_res["signature"] == "Work Signature\nAcme Corp"

    # Global user settings remain unchanged
    global_res = client.get("/api/v1/settings", headers=H(user)).json()
    assert global_res["sender_name"] == "Demo User"
    assert global_res["signature"] == "Default Signature"


def test_per_account_settings_patch_via_account_endpoint(client, db, account_world):
    user, acc = account_world

    client.patch("/api/v1/settings", headers=H(user), json={
        "sender_name": "Demo User",
        "signature": "Default Signature",
    })

    # Patch via /accounts/{account_id}/settings
    patched = client.patch(
        f"/api/v1/accounts/{acc.id}/settings",
        headers=H(user),
        json={"sender_name": "Direct Account Alias"},
    ).json()
    assert patched["sender_name"] == "Direct Account Alias"
    # Signature falls back to default signature since it was not overridden
    assert patched["signature"] == "Default Signature"


def test_account_settings_isolation_and_not_found(client, db, account_world):
    user, acc = account_world

    # Another user
    other_user = User(email="other@demo.sift.local")
    db.add(other_user)
    db.commit()

    # Other user cannot access acc settings
    res = client.get(f"/api/v1/settings?account_id={acc.id}", headers=H(other_user))
    assert res.status_code == 404

    res2 = client.patch(f"/api/v1/settings?account_id={acc.id}", headers=H(other_user), json={"sender_name": "Hacker"})
    assert res2.status_code == 404

    res3 = client.get(f"/api/v1/accounts/{acc.id}/settings", headers=H(other_user))
    assert res3.status_code == 404

    # Non-existent account returns 404
    fake_id = uuid.uuid4()
    assert client.get(f"/api/v1/settings?account_id={fake_id}", headers=H(user)).status_code == 404
    assert client.patch(f"/api/v1/settings?account_id={fake_id}", headers=H(user), json={"sender_name": "X"}).status_code == 404


def test_compose_sender_resolution_uses_account_settings(db, account_world):
    from app.api.compose import _from

    user, acc = account_world
    user_settings.update(db, user.id, {"sender_name": "Global Name"})
    email, sender = _from(db, user, acc)
    assert sender == "Global Name"

    # Override for account
    user_settings.update(db, user.id, {"sender_name": "Work Name"}, account_id=acc.id)
    email, sender = _from(db, user, acc)
    assert sender == "Work Name"
