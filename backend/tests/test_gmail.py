import httpx
import pytest

from app.mail.base import AuthRevoked, CursorExpired
from app.mail.gmail import GmailProvider


def provider(routes: dict):
    """routes: {(method, path-suffix, pageToken or None): (status, json)}"""
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        key = (request.method, request.url.path.rsplit("/me", 1)[1], request.url.params.get("pageToken"))
        status, body = routes[key]
        return httpx.Response(status, json=body)

    return GmailProvider("access", client=httpx.Client(transport=httpx.MockTransport(handler))), calls


def added(mid, *labels):
    return {"messagesAdded": [{"message": {"id": mid, "threadId": "t" + mid, "labelIds": list(labels)}}]}


def test_profile():
    p, calls = provider({("GET", "/profile", None): (200, {"emailAddress": "Me@Gmail.com", "historyId": "123"})})
    prof = p.profile()
    assert (prof.email, prof.cursor) == ("me@gmail.com", 123)
    assert calls[0].headers["authorization"] == "Bearer access"


def test_list_changes_pages_dedupes_and_skips_own_mail():
    p, calls = provider({
        ("GET", "/history", None): (200, {"history": [added("a", "INBOX", "UNREAD"), added("s", "SENT")], "nextPageToken": "p2", "historyId": "150"}),
        ("GET", "/history", "p2"): (200, {"history": [added("a", "INBOX"), added("d", "DRAFT"), added("b", "INBOX", "CATEGORY_UPDATES"), added("self", "SENT", "INBOX")], "historyId": "160"}),
    })
    changes = p.list_changes(100)
    assert changes.message_ids == ["a", "b", "self"]  # mail to myself lands in INBOX and counts
    assert changes.cursor == 160
    assert calls[0].url.params["startHistoryId"] == "100"
    assert calls[0].url.params.get_list("historyTypes") == ["messageAdded", "labelAdded", "labelRemoved"]


def test_list_changes_reports_label_edits_in_order():
    p, _ = provider({("GET", "/history", None): (200, {"historyId": "120", "history": [
        {"labelsRemoved": [{"message": {"id": "a"}, "labelIds": ["UNREAD"]}]},
        {"labelsAdded": [{"message": {"id": "a"}, "labelIds": ["UNREAD", "STARRED"]}]},
    ]})})
    changes = p.list_changes(100)
    assert changes.message_ids == []
    assert changes.label_changes == [("a", [], ["UNREAD"]), ("a", ["UNREAD", "STARRED"], [])]


def test_list_changes_with_no_history_keeps_reported_cursor():
    p, _ = provider({("GET", "/history", None): (200, {"historyId": "101"})})
    changes = p.list_changes(100)
    assert (changes.message_ids, changes.cursor) == ([], 101)


def test_expired_cursor_raises():
    p, _ = provider({("GET", "/history", None): (404, {"error": {"message": "Requested entity was not found."}})})
    with pytest.raises(CursorExpired):
        p.list_changes(1)


def test_revoked_token_raises_auth_revoked():
    p, _ = provider({("GET", "/profile", None): (401, {"error": {"message": "Invalid Credentials"}})})
    with pytest.raises(AuthRevoked):
        p.profile()


def test_start_watch_sends_inbox_filter():
    p, calls = provider({("POST", "/watch", None): (200, {"historyId": "9", "expiration": "1767225600000"})})
    w = p.start_watch("projects/p/topics/t")
    assert (w.cursor, w.expires_at_ms) == (9, 1767225600000)
    import json
    assert json.loads(calls[0].content) == {"topicName": "projects/p/topics/t", "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"}
