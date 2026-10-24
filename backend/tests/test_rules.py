from datetime import UTC, datetime

import pytest

from app import rules as r


def ctx(**kw):
    base = dict(account_id="acc1", sender="alerts@kotak.com", authenticated_domain="kotak.com",
                subject="Rs 240.00 debited via UPI", labels=["INBOX", "CATEGORY_UPDATES"],
                headers={"list-unsubscribe": "<mailto:x>"}, has_attachment=False,
                received_at=datetime(2026, 10, 24, 18, 30, tzinfo=UTC))  # 00:00 IST next day
    base.update(kw)
    return r.MailContext(**base)


def rule(i, conditions, action="silent", **kw):
    return r.RuleView(id=i, position=kw.pop("position", i), enabled=kw.pop("enabled", True), conditions=conditions,
                      action={"type": action}, **kw)


BANK = {"all": [{"field": "sender_domain", "op": "in", "value": ["kotak.com"]},
                {"field": "subject", "op": "matches", "value": r"\b(debited|credited|upi)\b"}]}
FRAUD = {"any": [{"field": "subject", "op": "contains_any", "value": ["fraud", "blocked", "suspicious"]}]}


def test_first_match_wins_in_position_order():
    rules = [rule(2, BANK, "notify_urgent"), rule(1, BANK, "silent")]
    assert r.evaluate(rules, ctx()).rule_id == 1


def test_exception_skips_rule_and_falls_through():
    rules = [rule(1, BANK, "silent", exceptions=FRAUD), rule(2, {"field": "sender_domain", "op": "is", "value": "kotak.com"}, "notify_urgent")]
    m = r.evaluate(rules, ctx(subject="Card blocked: suspicious activity, Rs 18,500 debited"))
    assert (m.rule_id, m.action["type"]) == (2, "notify_urgent")
    assert r.evaluate(rules[:1], ctx(subject="Card blocked: suspicious activity, Rs 18,500 debited")) is None


def test_disabled_and_out_of_scope_rules_are_skipped():
    assert r.evaluate([rule(1, BANK, enabled=False)], ctx()) is None
    assert r.evaluate([rule(1, BANK, account_scope=["other"])], ctx()) is None
    assert r.evaluate([rule(1, BANK, account_scope=["acc1"])], ctx()).rule_id == 1


@pytest.mark.parametrize("cond", [
    {"field": "sender", "op": "is", "value": "alerts@kotak.com"},
    {"field": "sender_domain", "op": "is", "value": "kotak.com"},
])
def test_spoofed_sender_never_matches(cond):
    spoofed = ctx(authenticated_domain=None)  # display name / From says kotak, authentication failed
    assert not r.matches(cond, spoofed)
    assert r.matches(cond, ctx())


def test_subdomains_match_parent_domain():
    c = {"field": "sender_domain", "op": "is", "value": "kotak.com"}
    assert r.matches(c, ctx(authenticated_domain="alerts.kotak.com"))
    assert not r.matches(c, ctx(authenticated_domain="notkotak.com"))


@pytest.mark.parametrize("cond,expected", [
    ({"field": "subject", "op": "contains", "value": "DEBITED"}, True),
    ({"field": "subject", "op": "matches", "value": r"^Rs \d+"}, True),
    ({"field": "label", "op": "has", "value": "CATEGORY_UPDATES"}, True),
    ({"field": "header", "op": "present", "value": "List-Unsubscribe"}, True),
    ({"field": "has_attachment", "op": "is", "value": True}, False),
    ({"field": "account", "op": "in", "value": ["acc1", "acc2"]}, True),
    ({"not": {"field": "label", "op": "has", "value": "CATEGORY_UPDATES"}}, False),
    ({"any": [{"field": "label", "op": "has", "value": "X"}, {"field": "label", "op": "has", "value": "INBOX"}]}, True),
])
def test_leaf_operators(cond, expected):
    assert r.matches(cond, ctx()) is expected


def test_time_window_uses_local_time_and_overnight_ranges():
    night = {"field": "time", "op": "between", "value": ["22:00", "07:00"]}
    day = {"field": "time", "op": "between", "value": ["09:00", "18:00"]}
    assert r.matches(night, ctx())  # 00:00 IST
    assert not r.matches(day, ctx())


def test_body_is_loaded_only_when_a_rule_needs_it():
    calls = []

    def loader():
        calls.append(1)
        return "Your card is BLOCKED"
    c = ctx(body_loader=loader)
    assert r.evaluate([rule(1, BANK)], c).rule_id == 1
    assert calls == []
    assert r.matches({"field": "body", "op": "contains_any", "value": ["blocked"]}, c)
    assert r.matches({"field": "body", "op": "contains_any", "value": ["card"]}, c)
    assert calls == [1]  # cached
    assert r.needs_body({"all": [BANK, {"not": {"field": "body", "op": "contains_any", "value": ["x"]}}]})
    assert not r.needs_body(BANK)


@pytest.mark.parametrize("bad", [
    {}, {"field": "nope"}, {"all": []}, {"field": "subject", "op": "matches", "value": "("},
    {"field": "subject", "op": "matches", "value": "a" * 301}, {"field": "time", "op": "between", "value": ["9", "10"]},
])
def test_validation_rejects_bad_conditions(bad):
    with pytest.raises(r.RuleError):
        r.validate_condition(bad)


def test_validation_of_actions():
    r.validate_action({"type": "notify_urgent", "tag": "Bank"})
    with pytest.raises(r.RuleError):
        r.validate_action({"type": "delete"})
