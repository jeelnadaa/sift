"""Phase 3b: semantic search (brought forward from Phase 5). Gate, what is sent, ranking, filters, backfill."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import LlmCredential, Message, MessageEmbedding, TokenUsage
from app.search import semantic
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401  (fixtures)
from tests.test_rule_tools import H


def add(db, user, account, gid, subject, snippet="", status="processed", priority="normal", days_ago=0, summary=None):
    m = Message(user_id=user.id, account_id=account.id, gmail_id=gid, thread_id=f"t-{gid}", sender=f"{gid}@example.com",
                sender_name="Someone", authenticated_domain="example.com", subject=subject, snippet=snippet, status=status,
                priority=priority, received_at=datetime.now(UTC) - timedelta(days=days_ago),
                extraction={"summary": summary} if summary else None)
    db.add(m)
    db.flush()
    return m


def test_ai_off_never_embeds_and_semantic_search_says_why(client, db, setup, fake_llm):
    user, account, provider, msgs = setup
    for m in msgs.values():
        run(db, account, provider, m)
    assert getattr(fake_llm, "embed_calls", []) == [] and db.scalar(select(func.count()).select_from(MessageEmbedding)) == 0
    r = client.get("/api/v1/search/semantic", headers=H(user), params={"q": "job offers"})
    assert r.status_code == 409 and "AI key" in r.json()["detail"]
    assert db.scalar(select(TokenUsage)) is None


def test_new_mail_is_indexed_without_bodies_and_redacted(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["recruiter"])
    texts = [t for c in fake_llm.embed_calls for t in c["texts"]]
    assert len(texts) == 1 and fake_llm.embed_calls[0]["task"] == "RETRIEVAL_DOCUMENT"
    t = texts[0]
    # subject and Gmail's preview go; the rest of the body (after the preview) never does
    assert "Backend role at Globex" in t and "Talent, Globex" not in t and "98765" not in t
    assert db.scalar(select(func.count()).select_from(MessageEmbedding)) == 1
    assert db.scalar(select(TokenUsage).where(TokenUsage.purpose == "embed")) is not None


def test_personal_details_are_redacted_before_embedding(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    m = add(db, user, account, "p", "Call me", snippet="Reach me at +91 98765 43210 or priya.s@globex.com")
    semantic.index(db, user.id, [m])
    t = fake_llm.embed_calls[-1]["texts"][0]
    assert "98765" not in t and "priya.s@globex.com" not in t


def test_search_by_meaning_ranks_and_applies_filters(client, db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    offer = add(db, user, account, "a", "Offer letter: Software Engineer role", "Job offer for the position, interview done", priority="urgent")
    add(db, user, account, "b", "Your UPI payment receipt", "Rs 240 debited")
    add(db, user, account, "c", "Hiring: backend position open", "Recruiter here, role and interview")
    add(db, user, account, "d", "Weekend sale on shoes", "Up to 50% off")
    db.commit()
    semantic.index(db, user.id, list(db.scalars(select(Message))))
    db.commit()

    r = client.get("/api/v1/search/semantic", headers=H(user), params={"q": "job offer"}).json()
    subjects = [i["subject"] for i in r["items"]]
    assert set(subjects[:2]) == {"Offer letter: Software Engineer role", "Hiring: backend position open"}
    assert "Weekend sale on shoes" not in subjects and all(i["score"] >= semantic.MIN_SCORE for i in r["items"])
    assert fake_llm.embed_calls[-1]["task"] == "RETRIEVAL_QUERY"

    r = client.get("/api/v1/search/semantic", headers=H(user), params={"q": "job offer priority:urgent"}).json()
    assert [i["id"] for i in r["items"]] == [str(offer.id)]  # Sift filters still apply

    r = client.get("/api/v1/search/semantic", headers=H(user), params={"q": "bank money"}).json()
    assert r["items"][0]["subject"] == "Your UPI payment receipt"


def test_backfill_covers_90_days_once_and_skips_silenced(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    add(db, user, account, "new", "Interview schedule", days_ago=10)
    add(db, user, account, "old", "Interview long ago", days_ago=200)
    add(db, user, account, "quiet", "Rs 99 debited", status="silenced", days_ago=5)
    db.commit()
    assert semantic.backfill(db, user.id) == 1
    assert semantic.backfill(db, user.id) == 0  # already indexed: nothing re-sent
    assert [t for c in fake_llm.embed_calls for t in c["texts"]][0].find("Interview schedule") >= 0
    s = semantic.status(db, user.id)
    assert (s["indexed"], s["recent_total"], s["backfill_days"]) == (1, 1, 90)


def test_backfill_stops_at_the_daily_cap(db, setup, fake_llm, override_settings):
    from app import user_settings
    user, account, provider, msgs = setup
    with_key(db, user)
    for i in range(5):
        add(db, user, account, f"m{i}", f"Interview round {i}", days_ago=i)
    db.commit()
    user_settings.update(db, user.id, {"daily_token_cap": 1})
    db.add(TokenUsage(user_id=user.id, day=datetime.now(UTC).date(), provider="gemini", model="m", purpose="extract", input_tokens=5, output_tokens=0))
    db.commit()
    assert semantic.backfill(db, user.id) == 0 and getattr(fake_llm, "embed_calls", []) == []


def test_saving_a_working_key_starts_the_backfill(client, db, setup, fake_llm, monkeypatch):
    from app import jobs
    user, *_ = setup
    queued = []
    monkeypatch.setattr(jobs, "enqueue_sync", lambda kind, payload, dedupe_key=None: queued.append(kind))
    r = client.put("/api/v1/ai/key", headers=H(user), json={"provider": "gemini", "model": "m", "api_key": "AIza-test-key-123"})
    assert r.status_code == 200 and queued == ["semantic_backfill"]
    assert db.scalar(select(LlmCredential)).status == "valid"


@pytest.mark.parametrize("q", ["priority:urgent", "   "])
def test_semantic_needs_words(client, db, setup, fake_llm, q):
    user, *_ = setup
    with_key(db, user)
    assert client.get("/api/v1/search/semantic", headers=H(user), params={"q": q}).status_code == 422
