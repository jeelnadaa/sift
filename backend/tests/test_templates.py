"""Tests for reply templates (canned replies) CRUD and tenant isolation."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import templates as template_service
from app.models import User
from app.security import create_token
from tests.test_pipeline import setup, fake_llm, run, with_key  # noqa: F401


def _auth_headers(user: User) -> dict[str, str]:
    token = create_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_template_crud(client: TestClient, db: Session, setup) -> None:
    user, _, _, _ = setup
    headers = _auth_headers(user)

    # 1. Initially empty
    res = client.get("/api/v1/templates", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["templates"] == []

    # 2. Create template
    payload = {
        "title": "Interview Availability",
        "body": "Thank you for reaching out! I am available on Thursday between 2 PM and 5 PM.",
        "shortcut": "avail",
    }
    create_res = client.post("/api/v1/templates", json=payload, headers=headers)
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["title"] == payload["title"]
    assert created["body"] == payload["body"]
    assert created["shortcut"] == "/avail"  # normalized with leading slash
    template_id = created["id"]

    # 3. List contains created
    list_res = client.get("/api/v1/templates", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1
    assert list_res.json()["templates"][0]["id"] == template_id

    # 4. Get by ID
    get_res = client.get(f"/api/v1/templates/{template_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["title"] == payload["title"]

    # 5. Patch template
    patch_payload = {
        "title": "Updated Availability",
        "body": "Available on Friday now.",
        "shortcut": "/fri",
    }
    patch_res = client.patch(f"/api/v1/templates/{template_id}", json=patch_payload, headers=headers)
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["title"] == "Updated Availability"
    assert patched["body"] == "Available on Friday now."
    assert patched["shortcut"] == "/fri"

    # 6. Delete template
    del_res = client.delete(f"/api/v1/templates/{template_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True

    # 7. Verify 404 after deletion
    not_found = client.get(f"/api/v1/templates/{template_id}", headers=headers)
    assert not_found.status_code == 404


def test_template_tenant_isolation(client: TestClient, db: Session, setup) -> None:
    user, _, _, _ = setup
    headers_a = _auth_headers(user)

    # Create user B
    user_b = User(email="user_b@demo.sift.local", password_hash="dummy")
    db.add(user_b)
    db.commit()
    db.refresh(user_b)
    headers_b = _auth_headers(user_b)

    # User A creates template
    created = template_service.create_template(
        db=db,
        user_id=user.id,
        title="Secret Template",
        body="Confidential text",
        shortcut="/secret",
    )

    # User B list cannot see User A's template
    res_b = client.get("/api/v1/templates", headers=headers_b)
    assert res_b.status_code == 200
    assert res_b.json()["total"] == 0

    # User B cannot get User A's template
    get_b = client.get(f"/api/v1/templates/{created.id}", headers=headers_b)
    assert get_b.status_code == 404

    # User B cannot patch User A's template
    patch_b = client.patch(f"/api/v1/templates/{created.id}", json={"title": "Hacked"}, headers=headers_b)
    assert patch_b.status_code == 404

    # User B cannot delete User A's template
    del_b = client.delete(f"/api/v1/templates/{created.id}", headers=headers_b)
    assert del_b.status_code == 404
