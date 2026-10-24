"""Phase 2b: rule preview, one-tap rules, suggestions, plain-English rules, onboarding scan, categories."""
import copy
import re
import uuid

import pytest
from sqlalchemy import select

from app import demo, rule_tools, scan
from app.mail.message import parse_metadata
from app.models import Fingerprint, GmailAccount, Message, OnboardingScan, Rule
from app.pipeline import process_message
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401  (fixtures)


def H(user):
    return {"Authorization": f"Bearer {create_token(user)}"}


def bank_mail(amount: str, date: str, subject: str | None = None) -> dict:
    m = copy.deepcopy(demo.samples()[2])
    for h in m["payload"]["headers"]:
        if h["name"] == "Subject":
            h["value"] = subject or f"Rs {amount} debited from your account via UPI on {date}"
    m["id"] = f"bank-{uuid.uuid4().hex[:8]}"
    return m


def process(db, account, m):
    return process_message(db, db.get(GmailAccount, account.id), demo.DemoProvider([m]), m["id"])


# ---- template regex ---------------------------------------------------------------------------

def test_template_regex_matches_the_same_template_only():
    rx = rule_tools.template_regex("Rs 240.00 debited from your account via UPI on 24-10-2026")
    for s in ["Rs 1,180.50 debited from your account via UPI on 25-10-2026", "Re: Rs 9 debited from your account via UPI on 1/1/26"]:
        assert re.search(rx, s, re.I), s
    for s in ["Card blocked: suspicious activity", "Rs 240 credited to your account via UPI on 24-10-2026"]:
        assert not re.search(rx, s, re.I), s


# ---- preview ------------------------------------------------------------------------------------

def test_preview_counts_matches_over_stored_mail(db, setup, client):
    user, account, provider, msgs = setup
    for m in msgs.values():
        run(db, account, provider, m)
    r = client.post("/api/v1/rules/preview", headers=H(user), json={"conditions": {"field": "sender_domain", "op": "is", "value": "kotak.com"}}).json()
    assert (r["checked"], r["matches"], r["body_not_previewed"]) == (5, 2, False)
    r = client.post("/api/v1/rules/preview", headers=H(user), json={"conditions": {"field": "header", "op": "present", "value": "List-Id"}}).json()
    assert r["matches"] == 1 and r["samples"][0]["subject"].startswith("Acme Corp campus drive")
    r = client.post("/api/v1/rules/preview", headers=H(user), json={"conditions": {"field": "body", "op": "contains_any", "value": ["x"]}}).json()
    assert r["body_not_previewed"] is True
    assert client.post("/api/v1/rules/preview", headers=H(user), json={"conditions": {"field": "nope"}}).status_code == 422


# ---- one-tap rules ------------------------------------------------------------------------------

def test_ignore_like_this_silences_the_template_but_not_fraud_alerts(db, setup, client, fcm_sends):
    user, account, provider, msgs = setup
    db.execute(Rule.__table__.delete())  # no starter rule: the bank mail notifies first
    db.commit()
    first = process(db, account, bank_mail("240.00", "24-10-2026"))
    assert first.notified
    r = client.post(f"/api/v1/messages/{first.message_id}/like-this", headers=H(user), json={"action": "silent"}).json()
    assert r["rule_id"] and r["preview"]["matches"] == 1
    rule = db.get(Rule, uuid.UUID(r["rule_id"]))
    assert rule.origin == "one_tap" and rule.conditions["all"][0] == {"field": "sender_domain", "op": "is", "value": "kotak.com"}

    db.execute(Fingerprint.__table__.update().values(last_action=None))  # prove the rule alone does it
    db.commit()
    nxt = process(db, account, bank_mail("1,180.50", "25-10-2026"))
    assert (nxt.priority, nxt.decided_by, nxt.notified) == ("silent", "rule", False)
    fraud = process(db, account, bank_mail("", "", subject="Card blocked due to suspicious activity"))
    assert fraud.notified


def test_one_tap_refuses_unverified_senders(db, setup, client):
    user, account, provider, msgs = setup
    m = msgs["recruiter"]
    m["payload"]["headers"] = [h for h in m["payload"]["headers"] if h["name"] != "Authentication-Results"]
    out = run(db, account, provider, m)
    r = client.post(f"/api/v1/messages/{out.message_id}/like-this", headers=H(user), json={})
    assert r.status_code == 422 and "can't verify" in r.json()["detail"]


def test_not_like_this_brings_mail_back_and_stops_the_template(db, setup, client):
    user, account, provider, msgs = setup
    out = run(db, account, provider, msgs["bank"])  # silenced by the starter rule
    r = client.post(f"/api/v1/messages/{out.message_id}/unsilence", headers=H(user)).json()
    assert r["rule_id"]  # reported so the user can edit it; never changed silently
    db.expire_all()
    m = db.get(Message, out.message_id)
    assert (m.status, m.priority) == ("processed", "normal")
    assert db.scalar(select(Fingerprint.last_action)) == "keep"
    assert client.post(f"/api/v1/messages/{out.message_id}/unsilence", headers=H(user)).status_code == 409


# ---- repeat-template suggestions ----------------------------------------------------------------

def test_repeated_template_is_suggested_then_accepted_or_dismissed(db, setup, client):
    user, account, provider, msgs = setup
    db.execute(Rule.__table__.delete())
    db.commit()
    for i in range(5):
        process(db, account, bank_mail(f"{100 + i}.00", f"2{i}-10-2026"))
    [s] = client.get("/api/v1/rules/suggestions", headers=H(user)).json()
    assert s["domain"] == "kotak.com" and s["count"] == 5
    rule = client.post(f"/api/v1/rules/suggestions/{s['id']}/accept", headers=H(user), json={"action": "silent"}).json()
    assert rule["origin"] == "suggestion" and rule["action"]["type"] == "silent"
    assert client.get("/api/v1/rules/suggestions", headers=H(user)).json() == []


def test_templates_that_carried_urgent_mail_are_never_suggested(db, setup, client):
    user, account, provider, msgs = setup
    db.execute(Rule.__table__.delete())
    db.commit()
    for i in range(5):
        process(db, account, bank_mail(f"{100 + i}.00", f"2{i}-10-2026"))
    db.execute(Message.__table__.update().values(priority="urgent"))
    db.commit()
    assert client.get("/api/v1/rules/suggestions", headers=H(user)).json() == []


def test_dismissed_suggestion_stays_away(db, setup, client):
    user, account, provider, msgs = setup
    db.execute(Rule.__table__.delete())
    db.commit()
    for i in range(5):
        process(db, account, bank_mail(f"{100 + i}.00", f"2{i}-10-2026"))
    [s] = client.get("/api/v1/rules/suggestions", headers=H(user)).json()
    assert client.post(f"/api/v1/rules/suggestions/{s['id']}/dismiss", headers=H(user)).status_code == 204
    process(db, account, bank_mail("999.00", "29-10-2026"))
    assert client.get("/api/v1/rules/suggestions", headers=H(user)).json() == []


# ---- plain-English rules --------------------------------------------------------------------------

def test_plain_english_rule_needs_a_key(db, setup, client, fake_llm):
    user, *_ = setup
    r = client.post("/api/v1/rules/from-text", headers=H(user), json={"text": "silence swiggy offers"})
    assert r.status_code == 422 and "API key" in r.json()["detail"] and fake_llm.calls == []


def test_plain_english_rule_becomes_a_reviewable_draft(db, setup, client, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["bank"])
    fake_llm.rule = {"name": "Bank mail silent unless it matters", "match": "all",
                     "conditions": [{"field": "sender_domain", "op": "in", "values": ["kotak.com", "slice.bank.in"]}],
                     "exception_groups": [
                         {"conditions": [{"field": "subject", "op": "contains_any", "values": ["fraud", "scam", "blocked", "suspicious"]}]},
                         {"conditions": [{"field": "subject", "op": "contains_any", "values": ["debited", "spent"]}, {"field": "amount", "op": "gt", "values": ["2,000"]}]},
                         {"conditions": [{"field": "subject", "op": "contains_any", "values": ["credited"]}, {"field": "amount", "op": "gt", "values": ["10000"]}]},
                     ], "action": "silent", "notes": []}
    r = client.post("/api/v1/rules/from-text", headers=H(user), json={"text": "ignore bank mail unless scam, debit above 2000 or credit above 10000"}).json()
    d = r["draft"]
    assert d["conditions"]["all"][0] == {"field": "sender_domain", "op": "in", "value": ["kotak.com", "slice.bank.in"]}
    groups = d["exceptions"]["any"]
    assert groups[1] == {"all": [{"field": "subject", "op": "contains_any", "value": ["debited", "spent"]}, {"field": "amount", "op": "gt", "value": 2000}]}
    assert "kotak.com (Kotak Mahindra Bank" in fake_llm.calls[-1]["prompt"]  # the model sees the user's real senders
    assert db.scalar(select(Rule).where(Rule.name.like("Bank mail%"))) is None  # not saved until confirmed
    saved = client.post("/api/v1/rules", headers=H(user), json={**d, "origin": "english", "enabled": True}).json()
    assert saved["origin"] == "english"

    # the saved rule behaves as the sentence says
    db.execute(Rule.__table__.delete().where(Rule.origin == "starter"))
    db.commit()
    small = process(db, account, bank_mail("240.00", "24-10-2026"))
    big = process(db, account, bank_mail("18,500.00", "24-10-2026"))
    fraud = process(db, account, bank_mail("", "", subject="Card blocked due to suspicious activity"))
    assert (small.priority, big.notified, fraud.notified) == ("silent", True, True)

    fake_llm.rule = None  # model says it is not a rule
    assert client.post("/api/v1/rules/from-text", headers=H(user), json={"text": "what's the weather"}).status_code == 422


def test_broad_plain_english_rule_is_flagged(db, setup, client, fake_llm):
    user, *_ = setup
    with_key(db, user)
    fake_llm.rule = {"name": "banking_rules", "match": "all", "conditions": [{"field": "label", "op": "has", "values": ["CATEGORY_UPDATES"]}],
                     "exception_groups": [], "action": "silent", "notes": []}
    r = client.post("/api/v1/rules/from-text", headers=H(user), json={"text": "ignore banking emails"}).json()
    assert any("Very broad" in n for n in r["draft"]["notes"])


def test_preview_flags_important_mail_a_rule_would_quiet(db, setup, client, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    for m in msgs.values():
        run(db, account, provider, m)
    r = client.post("/api/v1/rules/preview", headers=H(user), json={"conditions": {"field": "label", "op": "has", "value": "CATEGORY_UPDATES"}}).json()
    assert r["matches"] == 4 and r["important_matches"] == 3  # placement, HirePro, fraud alert
    assert r["samples"][0]["important"] is True


# ---- onboarding scan -------------------------------------------------------------------------------

class ScanMailbox(demo.DemoProvider):
    def list_message_ids(self, query, limit):
        assert "newer_than:30d" in query
        return list(self._by_id)[:limit]


def test_onboarding_scan_groups_senders_without_bodies_and_applies_rules(db, setup, client, monkeypatch):
    user, account, provider, msgs = setup
    from app import accounts
    from app.mail import google_oauth
    from app import crypto
    acc = db.get(GmailAccount, account.id)
    acc.encrypted_refresh_token = crypto.encrypt("rt")
    db.commit()
    mails = [bank_mail(f"{i}.00", "24-10-2026") for i in range(3)] + [msgs["placement"], msgs["recruiter"]]
    promo = copy.deepcopy(msgs["recruiter"])
    promo["id"], promo["labelIds"] = "promo-1", ["INBOX", "CATEGORY_PROMOTIONS"]
    promo["payload"]["headers"] = [h if h["name"] != "From" else {"name": "From", "value": "Swiggy <offers@swiggy.in>"} for h in promo["payload"]["headers"]]
    promo["payload"]["headers"] = [h if h["name"] != "Authentication-Results" else {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.i=@swiggy.in"} for h in promo["payload"]["headers"]]
    box = ScanMailbox(mails + [promo])
    full_calls = []
    monkeypatch.setattr(box, "get_full", lambda mid: full_calls.append(mid))
    monkeypatch.setattr(accounts, "provider_factory", lambda token: box)
    monkeypatch.setattr(google_oauth, "refresh_access_token", lambda rt: ("at", 3600))
    monkeypatch.setattr(scan, "PER_MINUTE", 10_000)
    accounts._token_cache.clear()

    started = client.post(f"/api/v1/accounts/{account.id}/scan", headers=H(user)).json()
    scan.run(started["id"])
    result = client.get(f"/api/v1/accounts/{account.id}/scan", headers=H(user)).json()
    assert result["status"] == "done" and result["scanned"] == 6 and full_calls == []  # headers only
    by_key = {s["key"]: s for s in result["senders"]}
    assert by_key["kotak.com"]["count"] == 3
    assert by_key["swiggy.in"]["suggested"] == "silent" and "promotions" in by_key["swiggy.in"]["hints"]
    assert db.scalar(select(Message).where(Message.gmail_id == "promo-1")) is None  # nothing stored per mail

    r = client.post(f"/api/v1/scans/{started['id']}/apply", headers=H(user),
                    json={"assignments": {"kotak.com": "silent", "swiggy.in": "silent", "univ.edu": "notify_urgent", "globex.com": "keep"}}).json()
    rules = {x["action"]["type"]: x for x in r["rules"]}
    assert set(rules) == {"silent", "notify_urgent"}
    assert rules["silent"]["conditions"]["any"][0]["value"] == ["kotak.com", "swiggy.in"]
    assert rules["silent"]["exceptions"] == scan.SECURITY_EXCEPTION  # fraud alerts still get through
    assert rules["notify_urgent"]["exceptions"] is None


def test_scan_of_a_revoked_account_fails_cleanly(db, setup, monkeypatch):
    user, account, provider, msgs = setup
    from app import accounts, crypto
    from app.mail import google_oauth
    from app.mail.base import AuthRevoked
    acc = db.get(GmailAccount, account.id)
    acc.encrypted_refresh_token = crypto.encrypt("rt")
    db.commit()
    monkeypatch.setattr(google_oauth, "refresh_access_token", lambda rt: (_ for _ in ()).throw(AuthRevoked("invalid_grant")))
    accounts._token_cache.clear()
    s = scan.start(db, db.get(GmailAccount, account.id))
    db.commit()
    scan.run(s.id)
    db.expire_all()
    assert db.get(OnboardingScan, s.id).status == "failed"
    assert db.get(GmailAccount, account.id).status == "needs_reconnect"


# ---- custom categories --------------------------------------------------------------------------------

def test_custom_categories(db, setup, client, fake_llm):
    user, account, provider, msgs = setup
    body = {"name": "Hackathons", "definition": "Hackathon invites, registrations and results"}
    created = client.post("/api/v1/categories", headers=H(user), json=body).json()
    assert created["name"] == "Hackathons"
    assert client.post("/api/v1/categories", headers=H(user), json={**body, "name": "hackathons"}).status_code == 409
    assert client.post("/api/v1/categories", headers=H(user), json={**body, "name": "Recruiter"}).status_code == 409
    assert client.post("/api/v1/categories", headers=H(user), json={**body, "name": "<script>"}).status_code == 422
    names = [c["name"] for c in client.get("/api/v1/categories", headers=H(user)).json()]
    assert "placement_announcement" in names and "Hackathons" in names
    with_key(db, user)
    run(db, account, provider, msgs["recruiter"])
    assert "- Hackathons: Hackathon invites" in fake_llm.calls[-1]["system"]  # the model is told about it
    assert client.delete(f"/api/v1/categories/{created['id']}", headers=H(user)).status_code == 204


@pytest.mark.parametrize("hints,expected", [
    ({"promotions", "bulk"}, "silent"),
    ({"social", "bulk"}, "digest"),
    ({"bulk"}, "keep"),          # a placement cell mailing through a list
    ({"no_reply"}, "keep"),      # an assessment platform's no-reply address
    (set(), "keep"),
])
def test_scan_suggestions_never_demote_on_weak_signals(hints, expected):
    assert scan.suggest(hints) == expected


def test_quieting_drafts_always_get_a_security_exception(db, setup, client, fake_llm):
    user, *_ = setup
    with_key(db, user)
    fake_llm.rule = {"name": "Banks", "match": "all", "conditions": [{"field": "sender_domain", "op": "in", "values": ["kotak.com"]}],
                     "exception_groups": [{"conditions": [{"field": "subject", "op": "contains_any", "values": ["urgent", "alert"]}]}],
                     "action": "silent", "notes": []}
    d = client.post("/api/v1/rules/from-text", headers=H(user), json={"text": "silence bank mail unless urgent"}).json()["draft"]
    first = d["exceptions"]["any"][0]
    assert "fraud" in first["value"] and "scam" in first["value"] and "otp" in first["value"]
    assert any("safety exception" in n for n in d["notes"])
    assert d["exceptions"]["any"][1]["value"] == ["urgent", "alert"]  # the user's own exception kept

    fake_llm.rule = {**fake_llm.rule, "action": "notify_urgent"}  # not quieting: nothing added
    d = client.post("/api/v1/rules/from-text", headers=H(user), json={"text": "kotak mail is urgent"}).json()["draft"]
    assert d["exceptions"]["any"][0]["value"] == ["urgent", "alert"]
