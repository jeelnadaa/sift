"""Pipeline behaviour, including the Phase 1 acceptance criteria:
- a priority mail notifies; a silenced bank mail produces no notification and no LLM call;
- with no API key, mail is delivered as normal priority and zero LLM calls are made."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import crypto, demo, notify
from app.llm import service as llm
from app.llm.base import LlmAuthError, LlmResult
from app.mail.gmail import GmailError
from app.models import Device, Fingerprint, GmailAccount, LlmCredential, Message, Notification, Rule, TokenUsage, User
from app.pipeline import process_message


class FakeLlm:
    """Stands in for Gemini. Records every call; classifies by keywords."""
    name = "fake"

    def __init__(self):
        self.calls = []
        self.fail_with = None
        self.raw = None
        self.override = {}

    # words that mean the same thing land on the same axis, so "job offer" finds "offer letter"
    SYNONYMS = {"offer": "job", "hiring": "job", "role": "job", "recruiter": "job", "interview": "job", "position": "job",
                "debited": "money", "credited": "money", "upi": "money", "bank": "money", "payment": "money", "rs": "money",
                "test": "exam", "assessment": "exam", "quiz": "exam"}

    def embed(self, texts, task, model, dims):
        import hashlib
        import re as _re
        self.embed_calls = getattr(self, "embed_calls", []) + [{"texts": list(texts), "task": task}]
        if self.fail_with:
            raise self.fail_with
        out = []
        for t in texts:
            v = [0.0] * dims
            for w in _re.findall(r"[a-z]+", t.lower()):
                w = self.SYNONYMS.get(w, w)
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dims] += 1.0
            out.append(v)
        return out

    def generate_json(self, system, prompt, schema, max_output_tokens=600):
        self.calls.append({"system": system, "prompt": prompt})
        if self.fail_with:
            raise self.fail_with
        if system.startswith("You turn a person's description"):
            q = getattr(self, "search_query", "from:walmart newer_than:7d")
            return LlmResult(text=json.dumps({"query": q, "explanation": "Mail from Walmart in the last 7 days"}), input_tokens=90, output_tokens=20)
        if system.startswith("You file one email into a subfolder"):
            return LlmResult(text=json.dumps({"folder": getattr(self, "sort_folder", "Course Updates")}), input_tokens=50, output_tokens=5)
        if system.startswith("You draft an email reply"):
            return LlmResult(text=json.dumps({"body": "Thanks, I'll attend. [your availability]"}), input_tokens=200, output_tokens=20)
        if system.startswith("Convert the user's sentence"):
            rule = getattr(self, "rule", None) or {"name": "invalid", "match": "all", "conditions": [], "exceptions": [], "action": "silent"}
            return LlmResult(text=json.dumps(rule), input_tokens=120, output_tokens=40)
        p = prompt.lower()
        if "campus drive" in p:
            out = {"category": "placement_announcement", "company": "Acme Corp", "platform": None, "deadline": "set",
                   "links": [{"url": "https://forms.univ.edu/acme", "label": "Register"}], "action_needed": True,
                   "priority": "normal", "summary": "Acme Corp campus drive, register by Wednesday", "confidence": 0.9}
        elif "assessment" in p or "suspicious" in p:
            out = {"category": "assessment_link" if "assessment" in p else "action_needed", "company": "Acme Corp" if "acme" in p else None,
                   "platform": "HirePro" if "hirepro" in p else None, "deadline": "2026-10-24T23:59:00+05:30",
                   "links": [{"url": "https://assess.hirepro.in/t/8dk2Q", "label": "Start test"}], "action_needed": True,
                   "priority": "urgent", "summary": "Assessment link live, closes tonight", "confidence": 0.9}
        else:
            out = {"category": "recruiter", "company": "Globex", "platform": None, "deadline": None, "links": [],
                   "action_needed": False, "priority": "normal", "summary": "Recruiter wants a call", "confidence": 0.8}
        out.setdefault("deadline", None)
        if out.get("deadline"):
            out["deadline"] = (datetime.now(UTC) + timedelta(days=3)).isoformat()  # always in the future
        out.update(self.override)
        out.setdefault("opportunity", self._choose(prompt, out.get("company")))
        return LlmResult(text=self.raw if self.raw is not None else json.dumps(out), input_tokens=300, output_tokens=60)

    @staticmethod
    def _choose(prompt, company):
        """Like the real model: pick a listed opportunity by name, else "new" / "unsure"."""
        import re
        for key, name in re.findall(r"^- (o\d+): ([^(\n]+)", prompt, re.M):
            if company and company.lower().split()[0] in name.lower():
                return key
        return "new" if company else "unsure"

    def ping(self):
        pass


@pytest.fixture
def fake_llm(monkeypatch):
    f = FakeLlm()
    monkeypatch.setattr(llm, "provider_factory", lambda provider, key, model: f)
    return f


@pytest.fixture
def setup(db, keys, fcm_sends):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    db.add(Device(user_id=user.id, fcm_token="phone-token-123"))
    demo.ensure_starter_rules(db, user)
    account = demo.demo_account(db, user)
    db.commit()
    msgs = {m["id"].split("-")[1]: m for m in demo.samples()}
    return user, account, demo.DemoProvider(list(msgs.values())), msgs


def with_key(db, user, status="valid"):
    db.add(LlmCredential(user_id=user.id, provider="gemini", model="m", encrypted_api_key=crypto.encrypt("AIza-test-key"), key_last4="test", status=status))
    db.commit()


def run(db, account, provider, msg):
    return process_message(db, db.get(GmailAccount, account.id), provider, msg["id"])


# ---- AI off (no key) -------------------------------------------------------------------

def test_ai_off_makes_zero_llm_calls_and_delivers_as_normal(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    assert not llm.ai_enabled(db, user.id)
    outcomes = {k: run(db, account, provider, m) for k, m in msgs.items()}

    assert fake_llm.calls == []  # the gate: no provider call without a valid key
    assert db.scalar(select(TokenUsage)) is None
    assert outcomes["bank"].priority == "silent" and outcomes["bank"].decided_by == "rule" and not outcomes["bank"].notified
    for k in ("placement", "hirepro", "fraud", "recruiter"):
        assert (outcomes[k].priority, outcomes[k].decided_by, outcomes[k].notified) == ("normal", "default", True), k
    assert len(fcm_sends) == 4 and {s["priority"] for s in fcm_sends} == {"normal"}


@pytest.mark.parametrize("status", ["invalid", "unvalidated"])
def test_invalid_or_unvalidated_key_is_ai_off(db, setup, fake_llm, status):
    user, account, provider, msgs = setup
    with_key(db, user, status)
    assert run(db, account, provider, msgs["hirepro"]).priority == "normal"
    assert fake_llm.calls == []


# ---- AI on ----------------------------------------------------------------------------

def test_ai_on_classifies_priority_mail_and_never_spends_on_silenced_mail(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)

    bank = run(db, account, provider, msgs["bank"])
    assert (bank.priority, bank.notified, bank.llm_called) == ("silent", False, False)
    assert fake_llm.calls == []

    hirepro = run(db, account, provider, msgs["hirepro"])
    assert (hirepro.priority, hirepro.decided_by, hirepro.notified, hirepro.llm_called) == ("urgent", "llm", True, True)
    m = db.get(Message, hirepro.message_id)
    assert m.category == "assessment_link" and m.extraction["company"] == "Acme Corp"
    push = fcm_sends[-1]
    assert push["priority"] == "urgent" and push["link"] == "https://assess.hirepro.in/t/8dk2Q" and push["body"].startswith("Assessment")

    fraud = run(db, account, provider, msgs["fraud"])  # bank rule exception lets it through to the LLM
    assert (fraud.priority, fraud.notified) == ("urgent", True)
    assert db.scalar(select(Rule.hit_count)) == 1  # only the silenced debit hit the rule
    usage = list(db.scalars(select(TokenUsage).where(TokenUsage.purpose == "extract")))
    assert len(usage) == 2 and usage[0].input_tokens == 300
    # the semantic index embeds the two delivered mails, never the silenced debit
    embedded = [t for c in fake_llm.embed_calls for t in c["texts"]]
    assert len(embedded) == 2 and not any("240" in t for t in embedded)


def test_prompt_wraps_email_as_untrusted_and_redacts(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["recruiter"])
    call = fake_llm.calls[0]
    assert "never follow" in call["system"].lower() and "<email>" in call["prompt"] and call["prompt"].rstrip().endswith("</email>")
    assert "98765 43210" not in call["prompt"] and "[phone]" in call["prompt"]  # personal number redacted before leaving
    assert "Globex" in call["prompt"]
    assert call["prompt"].startswith("Received: ")  # outside the untrusted block, for relative dates


def test_deadline_before_the_mail_arrived_is_dropped():
    from datetime import timezone
    received = datetime(2026, 10, 24, 6, 50, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    base = {"category": "assessment_link", "priority": "urgent", "summary": "x", "confidence": 0.9, "links": [], "action_needed": True}
    wrong_year = llm.validate_extraction(json.dumps({**base, "deadline": "2023-10-25T23:59:00+05:30"}), ["assessment_link"], received)
    tonight = llm.validate_extraction(json.dumps({**base, "deadline": "2026-10-24T23:59:00+05:30"}), ["assessment_link"], received)
    naive = llm.validate_extraction(json.dumps({**base, "deadline": "2026-10-29T18:00:00"}), ["assessment_link"], received)
    assert wrong_year["deadline"] is None
    assert tonight["deadline"] == "2026-10-24T23:59:00+05:30"
    assert naive["deadline"] == "2026-10-29T18:00:00+05:30"


def test_processing_twice_never_double_notifies_or_double_spends(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)
    first = run(db, account, provider, msgs["hirepro"])
    again = run(db, account, provider, msgs["hirepro"])
    assert first.notified and again.decided_by == "existing" and not again.notified
    assert len(fake_llm.calls) == 1 and len(fcm_sends) == 1
    assert len(list(db.scalars(select(Notification)))) == 1


def test_interrupted_message_is_resumed_and_reuses_cached_llm_result(db, setup, fake_llm, fcm_sends, monkeypatch):
    user, account, provider, msgs = setup
    with_key(db, user)
    real = notify.notify_message
    monkeypatch.setattr(notify, "notify_message", lambda *a: (_ for _ in ()).throw(RuntimeError("crash after LLM")))
    with pytest.raises(RuntimeError):
        run(db, account, provider, msgs["hirepro"])
    db.rollback()
    assert db.scalar(select(Message.status)) == "processing"
    monkeypatch.setattr(notify, "notify_message", real)
    out = run(db, account, provider, msgs["hirepro"])
    assert out.notified and len(fake_llm.calls) == 1  # cached extraction, no second call


def test_bad_llm_output_is_retried_once_then_falls_back_to_normal(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    fake_llm.raw = "not json"
    out = run(db, account, provider, msgs["recruiter"])
    assert len(fake_llm.calls) == 2 and out.priority == "normal"
    assert db.get(Message, out.message_id).category == "other"


def test_revoked_llm_key_turns_ai_off_and_tells_the_user_once(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)
    fake_llm.fail_with = LlmAuthError("PERMISSION_DENIED")
    assert run(db, account, provider, msgs["recruiter"]).priority == "normal"
    assert db.scalar(select(LlmCredential.status)) == "invalid"
    assert [s["type"] for s in fcm_sends] == ["system", "mail"]
    run(db, account, provider, msgs["placement"])
    assert len(fake_llm.calls) == 1  # AI is off now
    assert [s["type"] for s in fcm_sends].count("system") == 1


def test_daily_cap_stops_llm_calls(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    from app import user_settings
    user_settings.update(db, user.id, {"daily_token_cap": 300})
    db.commit()
    run(db, account, provider, msgs["recruiter"])  # 360 tokens, now over the cap
    out = run(db, account, provider, msgs["placement"])
    assert len(fake_llm.calls) == 1 and out.priority == "normal" and out.notified


def test_model_cannot_demote_a_real_persons_mail_to_digest(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    fake_llm.override = {"priority": "digest", "confidence": 0.9}
    out = run(db, account, provider, msgs["recruiter"])  # a person: no list headers, not no-reply
    assert out.priority == "normal"


def test_model_may_send_bulk_mail_to_digest(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    fake_llm.override = {"priority": "digest", "confidence": 0.9}
    out = run(db, account, provider, msgs["placement"])  # mailing list (List-Id): weak bulk signal
    assert out.priority == "digest"


# ---- rules, fingerprints, dedupe, failures ------------------------------------------------

def test_spoofed_bank_mail_is_not_silenced_by_the_bank_rule(db, setup, fake_llm):
    user, account, provider, msgs = setup
    m = msgs["bank"]
    m["payload"]["headers"] = [h for h in m["payload"]["headers"] if h["name"] != "Authentication-Results"] + [
        {"name": "Authentication-Results", "value": "mx.google.com; dkim=fail header.i=@kotak.com; spf=fail smtp.mailfrom=evil.example; dmarc=fail header.from=kotak.com"}]
    out = run(db, account, provider, m)
    assert (out.priority, out.notified) == ("normal", True)


def test_fingerprint_silences_templates_the_user_silenced(db, setup, fake_llm):
    user, account, provider, msgs = setup
    out = run(db, account, provider, msgs["bank"])
    from app import rule_tools
    rule_tools.remember_template(db, db.get(Message, out.message_id), "silent")  # e.g. "ignore mails like this"
    db.scalar(select(Rule)).enabled = False
    db.commit()
    again = demo.samples()[2]  # another debit alert: new id, new Message-ID, same template
    out = process_message(db, db.get(GmailAccount, account.id), demo.DemoProvider([again]), again["id"])
    assert (out.priority, out.decided_by, out.notified) == ("silent", "fingerprint", False)


def test_templates_learned_from_rules_never_override_the_rule(db, setup, fake_llm):
    """Disabling a rule brings its mail back; a rule's exceptions are never undone by memory."""
    user, account, provider, msgs = setup
    run(db, account, provider, msgs["bank"])
    assert db.scalar(select(Fingerprint.last_action_source)) == "rule"
    db.scalar(select(Rule)).enabled = False
    db.commit()
    again = demo.samples()[2]
    out = process_message(db, db.get(GmailAccount, account.id), demo.DemoProvider([again]), again["id"])
    assert out.notified and out.decided_by != "fingerprint"


def test_same_mail_in_two_accounts_notifies_once(db, setup, fcm_sends):
    user, account, provider, msgs = setup
    other = GmailAccount(user_id=user.id, email="second@gmail.com", label="Second")
    db.add(other)
    db.commit()
    copy = {**msgs["recruiter"], "id": "second-copy"}
    run(db, account, provider, msgs["recruiter"])
    out = process_message(db, db.get(GmailAccount, other.id), demo.DemoProvider([copy]), "second-copy")
    assert out.decided_by == "duplicate" and len(fcm_sends) == 1


def test_promotions_go_to_digest_without_llm(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    m = msgs["recruiter"]
    m["labelIds"] = ["INBOX", "CATEGORY_PROMOTIONS"]
    out = run(db, account, provider, m)
    assert (out.priority, out.decided_by) == ("digest", "heuristic") and fake_llm.calls == []


def test_unexpected_error_still_delivers_as_normal(db, setup, monkeypatch, fcm_sends):
    user, account, provider, msgs = setup
    import app.pipeline as p
    monkeypatch.setattr(p.rules, "evaluate", lambda *a: (_ for _ in ()).throw(ValueError("bug")))
    out = run(db, account, provider, msgs["recruiter"])
    assert (out.priority, out.decided_by, out.notified) == ("normal", "error", True)


def test_transient_gmail_error_leaves_message_to_retry(db, setup, monkeypatch, fcm_sends):
    user, account, provider, msgs = setup
    calls = {"n": 0}
    real = provider.get_full

    def flaky(mid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise GmailError(503, "backend error")
        return real(mid)
    monkeypatch.setattr(provider, "get_full", flaky)
    bodyrule = Rule(user_id=user.id, name="needs body", position=0, conditions={"field": "body", "op": "contains_any", "value": ["zzz"]}, action={"type": "silent"})
    db.add(bodyrule)
    db.commit()
    with pytest.raises(GmailError):
        run(db, account, provider, msgs["recruiter"])
    db.rollback()
    out = run(db, account, provider, msgs["recruiter"])
    assert out.notified and len(fcm_sends) == 1


# ---- end to end through check_account (regression: account row lock blocked message inserts) ----

def test_check_account_runs_the_pipeline_without_deadlocking(db, setup, monkeypatch, fcm_sends):
    import threading

    from app import accounts
    from app.mail.base import Changes, Profile
    user, account, provider, msgs = setup
    acc = db.get(GmailAccount, account.id)
    acc.encrypted_refresh_token, acc.history_id = crypto.encrypt("rt"), 100
    db.commit()

    class Mailbox(demo.DemoProvider):
        def list_changes(self, since):
            return Changes([msgs["recruiter"]["id"], msgs["bank"]["id"]], 120)

        def profile(self):
            return Profile(account.email, 120)

    box = Mailbox(list(msgs.values()))
    monkeypatch.setattr(accounts, "provider_factory", lambda token: box)
    monkeypatch.setattr(accounts.google_oauth, "refresh_access_token", lambda rt: ("at", 3600))
    accounts._token_cache.clear()

    result = {}
    t = threading.Thread(target=lambda: result.setdefault("n", accounts.check_account(account.id)), daemon=True)
    t.start()
    t.join(timeout=20)
    assert not t.is_alive(), "check_account hung (lock conflict)"
    assert result["n"] == 2
    db.expire_all()
    assert db.get(GmailAccount, account.id).history_id == 120
    assert len(fcm_sends) == 1  # recruiter notified, bank silenced


# ---- re-send ------------------------------------------------------------------------------

def test_unacknowledged_urgent_notifications_are_resent_up_to_the_limit(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["hirepro"])
    n = db.scalar(select(Notification))
    assert notify.resend_unacknowledged(db) == 0  # too early

    for expected in (1, 2, 3):
        n.sent_at = datetime.now(UTC) - timedelta(minutes=6)
        db.commit()
        assert notify.resend_unacknowledged(db) == 1
        db.refresh(n)
        assert n.resend_count == expected
    n.sent_at = datetime.now(UTC) - timedelta(minutes=6)
    db.commit()
    assert notify.resend_unacknowledged(db) == 0  # limit of 3 reached
    assert [s.get("resend") for s in fcm_sends] == [None, 1, 2, 3]


def test_acknowledged_notifications_are_not_resent(db, setup, fake_llm, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["hirepro"])
    n = db.scalar(select(Notification))
    assert notify.acknowledge(db, user.id, n.id)
    n.sent_at = datetime.now(UTC) - timedelta(minutes=30)
    db.commit()
    assert notify.resend_unacknowledged(db) == 0


def test_mail_deleted_from_gmail_before_processing_is_skipped(db, setup):
    """Regression (2026-10-24): a mail gone from Gmail (404) made every check fail and retry
    forever, so mail after it was never processed."""
    from app.mail.gmail import GmailError
    user, account, provider, msgs = setup

    class Gone(demo.DemoProvider):
        def get_metadata(self, message_id):
            raise GmailError(404, "Requested entity was not found.")

    out = run(db, account, Gone([]), {"id": "deleted-1"})
    assert out.decided_by == "gone" and out.message_id is None
    assert run(db, account, provider, msgs["recruiter"]).notified  # the next mail goes through

def test_subject_line_personal_identifiers_are_redacted_before_llm(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    m = demo._msg("pii", "Acme HR <hr@acme.com>", "Interview for 21BCE1234 call +91 98765 43210", "Interview details", ["INBOX"])
    run(db, account, demo.DemoProvider([m]), m)
    assert len(fake_llm.calls) == 1
    sent_prompt = fake_llm.calls[0]["prompt"]
    assert "21BCE1234" not in sent_prompt
    assert "98765 43210" not in sent_prompt
    assert "[roll]" in sent_prompt
    assert "[phone]" in sent_prompt
