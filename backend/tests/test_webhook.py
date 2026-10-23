from sqlalchemy import select

from app.models import Job
from tests.test_pubsub import body

PUSH = body({"emailAddress": "me@gmail.com", "historyId": 99}, message_id="pubsub-1")


def jobs(db):
    return list(db.scalars(select(Job)))


def test_push_is_acknowledged_and_enqueued(client, db):
    r = client.post("/webhooks/gmail", json=PUSH)
    assert r.status_code == 204
    [job] = jobs(db)
    assert job.kind == "gmail_push"
    assert job.payload == {"email": "me@gmail.com", "history_id": 99, "pubsub_message_id": "pubsub-1"}


def test_redelivered_push_is_enqueued_once(client, db):
    client.post("/webhooks/gmail", json=PUSH)
    client.post("/webhooks/gmail", json=PUSH)
    assert len(jobs(db)) == 1


def test_malformed_push_is_acked_without_work(client, db):
    assert client.post("/webhooks/gmail", json={"message": {"data": "%%%"}}).status_code == 204
    assert client.post("/webhooks/gmail", content=b"not json", headers={"content-type": "application/json"}).status_code == 204
    assert jobs(db) == []


def test_push_without_token_is_rejected_when_verification_on(client, db, override_settings):
    override_settings(pubsub_verify=True)
    assert client.post("/webhooks/gmail", json=PUSH).status_code == 401
    assert client.post("/webhooks/gmail", json=PUSH, headers={"Authorization": "Bearer forged"}).status_code == 401
    assert jobs(db) == []


def test_prod_refuses_to_run_without_verification(client, override_settings):
    override_settings(env="prod", pubsub_verify=False)
    assert client.post("/webhooks/gmail", json=PUSH).status_code == 500
