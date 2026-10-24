"""Phase 3a: thread reader, sanitizing, image blocking and proxy, signed attachment links."""
import base64

import httpx
import pytest

from app import accounts as account_service
from app import reader, signing
from app.api import links
from app.models import User
from tests.test_pipeline import setup  # noqa: F401  (fixtures)
from tests.test_rule_tools import H


def b64(s: str | bytes) -> str:
    return base64.urlsafe_b64encode(s.encode() if isinstance(s, str) else s).decode().rstrip("=")


def mail(gmail_id="m1", thread="t1", html=None, text="Hello", attachments=(), charset="utf-8", date="Sat, 24 Oct 2026 10:00:00 +0530"):
    parts = [{"mimeType": "text/plain", "headers": [{"name": "Content-Type", "value": f"text/plain; charset={charset}"}],
              "body": {"data": b64(text.encode(charset))}}]
    if html is not None:
        parts.append({"mimeType": "text/html", "body": {"data": b64(html)}})
    body = {"mimeType": "multipart/alternative", "parts": parts}
    if attachments:
        body = {"mimeType": "multipart/mixed", "parts": [body, *attachments]}
    body["headers"] = [{"name": "From", "value": "Priya <priya@globex.com>"}, {"name": "To", "value": "me@gmail.com"},
                       {"name": "Subject", "value": "Hi"}, {"name": "Date", "value": date}]
    return {"id": gmail_id, "threadId": thread, "labelIds": ["INBOX", "UNREAD"], "internalDate": "1792816881570", "snippet": "Hello", "payload": body}


def att(name, mime, att_id, cid=None, size=10):
    headers = [{"name": "Content-ID", "value": f"<{cid}>"}] if cid else []
    return {"mimeType": mime, "filename": name, "headers": headers, "body": {"attachmentId": att_id, "size": size}}


# ---- sanitizing -------------------------------------------------------------------------------

def test_sanitize_removes_everything_active():
    dirty = ('<div onclick="steal()">Hi<script>alert(1)</script><img src="x" onerror="alert(2)">'
             '<a href="javascript:alert(3)">x</a><iframe src="https://evil"></iframe><form action="https://evil"><input></form>'
             '<base href="https://evil/"><meta http-equiv="refresh" content="0;url=https://evil"><link rel=stylesheet href="https://evil/x.css">'
             '<table bgcolor="#fff"><tr><td style="color:red">kept</td></tr></table><style>p{color:blue}</style></div>')
    clean = reader.sanitize(dirty)
    for bad in ("script", "onclick", "onerror", "javascript:", "iframe", "<form", "<input", "<base", "<meta", "<link", "steal"):
        assert bad not in clean.lower(), bad
    assert 'style="color:red"' in clean and "kept" in clean and "<style>" in clean and 'bgcolor="#fff"' in clean


def test_links_open_outside_and_leak_nothing():
    clean = reader.sanitize('<a href="https://example.com/x">x</a>')
    assert 'target="_blank"' in clean and "noopener" in clean and "noreferrer" in clean


# ---- images -----------------------------------------------------------------------------------

def test_remote_images_blocked_by_default_and_proxied_on_request(keys):
    html = '<img src="https://track.example.com/pixel.gif"><img src="cid:logo1"><td background="https://x.example/bg.png" style="background:url(https://x.example/a.png)">'
    off, blocked = reader.rewrite_images(html, False, "", {"logo1": "/api/v1/files/tok"})
    assert blocked == 1 and "track.example.com" not in off and "x.example" not in off and 'src="/api/v1/files/tok"' in off
    on, blocked = reader.rewrite_images(html, True, "", {})
    assert blocked == 0 and "https://track" not in on.split("/api/v1/img")[0]
    token = on.split("/api/v1/img?t=")[1].split('"')[0]
    assert signing.read("img", token)["u"] == "https://track.example.com/pixel.gif"


def test_signed_tokens_are_purpose_bound_tamper_proof_and_expire(keys):
    t = signing.make("img", {"u": "https://a"}, 60)
    with pytest.raises(signing.BadToken):
        signing.read("file", t)  # an image link can't open an attachment
    body, sig = t.split(".")
    forged = signing.make("img", {"u": "https://evil"}, 60).split(".")[0] + "." + sig
    with pytest.raises(signing.BadToken):
        signing.read("img", forged)
    old = signing.make("img", {"u": "https://a"}, -1)
    with pytest.raises(signing.BadToken):
        signing.read("img", old)


@pytest.mark.parametrize("url", ["http://127.0.0.1/x.png", "http://localhost/x.png", "http://10.0.0.5/x.png", "http://169.254.169.254/latest",
                                 "http://[::1]/x.png", "file:///etc/passwd", "http://user:pw@example.com/x.png", "http://example.com:22/x.png"])
def test_image_proxy_refuses_private_and_odd_addresses(url):
    with pytest.raises(links.Refused):
        links._check_public(url)


def test_image_proxy_fetches_only_real_images(monkeypatch):
    monkeypatch.setattr(links, "_check_public", lambda url: None if "ok.example" in url else (_ for _ in ()).throw(links.Refused("private")))

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/a.png":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"PNG")
        if path == "/page":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<script>")
        if path == "/svg":
            return httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=b"<svg/>")
        if path == "/big":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x" * (links.MAX_IMAGE_BYTES + 1))
        if path == "/hop":
            return httpx.Response(302, headers={"location": "http://internal.example/a.png"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    assert links.fetch_image("https://ok.example/a.png", client) == (b"PNG", "image/png")
    for path in ("/page", "/svg", "/big", "/hop", "/missing"):
        with pytest.raises(links.Refused):
            links.fetch_image(f"https://ok.example{path}", client)


# ---- parsing --------------------------------------------------------------------------------------

def test_walk_decodes_charsets_and_lists_attachments(keys):
    m = mail(text="Café crème", charset="iso-8859-1", html='<p>Logo <img src="cid:logo1"></p>',
             attachments=[att("logo.png", "image/png", "A1", cid="logo1"), att("offer.pdf", "application/pdf", "A2", size=2048)])
    out = reader.render_message(m, user_id="u", account_id="a", base="", images=False)
    assert out["text"] == "Café crème"
    assert [a["filename"] for a in out["attachments"]] == ["offer.pdf"]  # the inline logo is shown in the mail, not listed
    assert out["attachments"][0]["view_url"] is None and out["attachments"][0]["size"] == 2048
    assert "/api/v1/files/" in out["html"] and out["html_url"].startswith("/api/v1/render/")
    assert out["from"] == {"name": "Priya", "email": "priya@globex.com"} and out["date"].startswith("2026-10-24T10:00")


# ---- endpoints ------------------------------------------------------------------------------------

@pytest.fixture
def thread(db, setup, monkeypatch):
    user, account, provider, msgs = setup
    first = mail("g1", "thr", html='<p onclick="x()">First <img src="https://t.example/p.gif"></p>',
                 attachments=[att("cv.pdf", "application/pdf", "ATT1")])
    reply = mail("g2", "thr", text="Reply", date="Sat, 24 Oct 2026 11:00:00 +0530")
    reply["internalDate"] = "1792820481570"
    draft = mail("g3", "thr", text="draft")
    draft["labelIds"] = ["DRAFT"]

    class P:
        def get_thread(self, tid):
            assert tid == "thr"
            return {"messages": [reply, draft, first]}

        def get_full(self, gid):
            return {"g1": first, "g2": reply}[gid]

        def get_attachment(self, mid, aid):
            assert (mid, aid) == ("g1", "ATT1")
            return b"%PDF-1.4 cv"

    monkeypatch.setattr(account_service, "provider_for", lambda a: P())
    from app.models import Message
    msg = Message(user_id=user.id, account_id=account.id, gmail_id="g1", thread_id="thr", sender="priya@globex.com", subject="Hi", status="processed", priority="normal")
    db.add(msg)
    db.commit()
    return user, msg


def test_thread_endpoint_returns_safe_conversation(client, thread):
    user, msg = thread
    r = client.get(f"/api/v1/messages/{msg.id}/thread", headers=H(user), params={"images": False}).json()
    assert [m["gmail_id"] for m in r["messages"]] == ["g1", "g2"]  # oldest first, no drafts
    first = r["messages"][0]
    assert first["id"] == str(msg.id) and r["messages"][1]["id"] is None
    assert "html" not in first and first["html_url"] and first["images_blocked"] == 1
    assert [a["filename"] for a in first["attachments"]] == ["cv.pdf"]

    page = client.get(first["html_url"])
    assert page.status_code == 200 and "First" in page.text and "onclick" not in page.text and "t.example" not in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"] and "script" not in page.headers["content-security-policy"]

    with_images = client.get(f"/api/v1/messages/{msg.id}/thread", headers=H(user), params={"images": True}).json()
    page = client.get(with_images["messages"][0]["html_url"])
    assert "/api/v1/img?t=" in page.text and "https://t.example" not in page.text

    f = client.get(first["attachments"][0]["url"])
    assert f.content == b"%PDF-1.4 cv" and f.headers["content-disposition"].startswith("attachment;")
    assert f.headers["x-content-type-options"] == "nosniff" and "sandbox" in f.headers["content-security-policy"]


def test_links_are_private_to_their_owner(client, db, thread, keys):
    user, msg = thread
    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    assert client.get(f"/api/v1/messages/{msg.id}/thread", headers=H(other)).status_code == 404
    url = client.get(f"/api/v1/messages/{msg.id}/thread", headers=H(user)).json()["messages"][0]["attachments"][0]["url"]
    token = url.rsplit("/", 1)[1]
    d = signing.read("file", token)
    stolen = signing.make("file", {**d, "u": str(other.id)}, 60)  # someone else's user id: not their account
    assert client.get(f"/api/v1/files/{stolen}").status_code == 404
    assert client.get(f"/api/v1/files/{token[:-3]}abc").status_code == 403
    assert client.get("/api/v1/render/garbage").status_code == 403



def test_images_load_by_default_through_the_proxy_and_the_setting_turns_it_off(client, thread):
    user, msg = thread
    first = client.get(f"/api/v1/messages/{msg.id}/thread", headers=H(user)).json()["messages"][0]
    assert first["images_blocked"] == 0 and "/api/v1/img?t=" in client.get(first["html_url"]).text
    client.patch("/api/v1/settings", headers=H(user), json={"load_remote_images": False})
    first = client.get(f"/api/v1/messages/{msg.id}/thread", headers=H(user)).json()["messages"][0]
    assert first["images_blocked"] == 1 and "/api/v1/img" not in client.get(first["html_url"]).text
