"""Gmail implementation of MailProvider, over the Gmail REST API with httpx.

Quota (per user, per minute: 6,000 units): history.list = 2, messages.get = 20 (metadata) or 60 (full),
watch = 100. Polling every 5 s costs 24 units per account per minute.
"""
import base64
import json
import secrets

import httpx

from app.mail.base import AuthRevoked, Changes, CursorExpired, Profile, Watch
from app.mail.message import METADATA_HEADERS

API = "https://gmail.googleapis.com/gmail/v1/users/me"
UPLOAD = "https://gmail.googleapis.com/upload/gmail/v1/users/me"
SKIP_LABELS = {"DRAFT", "SENT"}  # mail I wrote is not "new mail"


class GmailError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


class GmailProvider:
    def __init__(self, access_token: str, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=20)
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def _call(self, method: str, path: str, **kw) -> dict:
        return self._handle(self._client.request(method, API + path, headers=self._headers, **kw))

    def _handle(self, r: httpx.Response) -> dict:
        if 200 <= r.status_code < 300:
            return r.json() if r.content else {}
        try:
            message = r.json().get("error", {}).get("message", "")
        except ValueError:
            message = r.text[:200]
        if r.status_code == 401:
            raise AuthRevoked(f"gmail 401: {message}")
        raise GmailError(r.status_code, message)

    def profile(self) -> Profile:
        p = self._call("GET", "/profile")
        return Profile(email=p["emailAddress"].lower(), cursor=int(p["historyId"]))

    def list_changes(self, since: int) -> Changes:
        ids: list[str] = []
        seen: set[str] = set()
        label_changes: list[tuple[str, list[str], list[str]]] = []
        params = {"startHistoryId": str(since), "historyTypes": ["messageAdded", "labelAdded", "labelRemoved"], "maxResults": "500"}
        cursor = since
        while True:
            try:
                page = self._call("GET", "/history", params=params)
            except GmailError as exc:
                if exc.status == 404:  # startHistoryId older than Gmail keeps (about a week)
                    raise CursorExpired(str(since)) from exc
                raise
            cursor = int(page.get("historyId", cursor))
            for h in page.get("history", []):
                for added in h.get("messagesAdded", []):
                    m = added["message"]
                    msg_labels = set(m.get("labelIds", []))
                    if m["id"] in seen or (msg_labels & SKIP_LABELS and "INBOX" not in msg_labels):
                        continue
                    seen.add(m["id"])
                    ids.append(m["id"])
                for change in h.get("labelsAdded", []):
                    label_changes.append((change["message"]["id"], change.get("labelIds", []), []))
                for change in h.get("labelsRemoved", []):
                    label_changes.append((change["message"]["id"], [], change.get("labelIds", [])))
            token = page.get("nextPageToken")
            if not token:
                return Changes(message_ids=ids, cursor=cursor, label_changes=label_changes)
            params["pageToken"] = token

    def list_message_ids(self, query: str, limit: int) -> list[str]:
        """Newest first, up to `limit` (messages.list: 5 units per page of up to 500)."""
        ids: list[str] = []
        params = {"q": query, "maxResults": "500"}
        while len(ids) < limit:
            page = self._call("GET", "/messages", params=params)
            ids.extend(m["id"] for m in page.get("messages", []))
            if not page.get("nextPageToken"):
                break
            params["pageToken"] = page["nextPageToken"]
        return ids[:limit]

    def search(self, query: str, page_token: str | None, page_size: int) -> tuple[list[dict], str | None, int]:
        """One page of Gmail search results, newest first: ([{id, threadId}], next page token,
        Gmail's estimate of the total). Spam and trash only when the query asks (in:spam)."""
        params = {"q": query, "maxResults": str(page_size)}
        if page_token:
            params["pageToken"] = page_token
        page = self._call("GET", "/messages", params=params)
        return page.get("messages", []), page.get("nextPageToken"), int(page.get("resultSizeEstimate") or 0)

    def get_metadata(self, message_id: str) -> dict:
        """Headers only (20 quota units). Never fetches the body."""
        params = [("format", "metadata")] + [("metadataHeaders", h) for h in METADATA_HEADERS]
        return self._call("GET", f"/messages/{message_id}", params=params)

    def get_full(self, message_id: str) -> dict:
        """Full message incl. body parts (60 units). Only when a rule or the LLM needs the body."""
        return self._call("GET", f"/messages/{message_id}", params={"format": "full"})

    def get_thread(self, thread_id: str) -> dict:
        """Whole conversation with bodies, for reading (10 units). Never stored."""
        return self._call("GET", f"/threads/{thread_id}", params={"format": "full"})

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Attachment bytes (5 units), streamed to the user and never stored."""
        data = self._call("GET", f"/messages/{message_id}/attachments/{attachment_id}").get("data", "")
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

    # ---- changing mail (needs gmail.modify; Phase 3c) -------------------------------------------

    def modify_thread(self, thread_id: str, add: list[str], remove: list[str]) -> None:
        """Add/remove labels on a whole conversation (archive = remove INBOX, read = remove UNREAD)."""
        self._call("POST", f"/threads/{thread_id}/modify", json={"addLabelIds": add, "removeLabelIds": remove})

    def modify_message(self, message_id: str, add: list[str], remove: list[str]) -> None:
        self._call("POST", f"/messages/{message_id}/modify", json={"addLabelIds": add, "removeLabelIds": remove})

    def trash_thread(self, thread_id: str) -> None:
        """Moves to Trash (Gmail deletes it for good after 30 days; Sift never deletes)."""
        self._call("POST", f"/threads/{thread_id}/trash")

    def untrash_thread(self, thread_id: str) -> None:
        self._call("POST", f"/threads/{thread_id}/untrash")

    def list_labels(self) -> list[dict]:
        return self._call("GET", "/labels").get("labels", [])

    def create_label(self, name: str) -> dict:
        return self._call("POST", "/labels", json={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"})

    # ---- drafts and sending (Phase 4; gmail.modify covers both) ------------------------------------

    def _upload(self, method: str, path: str, metadata: dict, raw: bytes) -> dict:
        """multipart/related upload: JSON metadata (e.g. the thread) + the whole message as
        message/rfc822, so large attachments don't need base64 inside JSON."""
        boundary = "sift-" + secrets.token_hex(12)
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n"
                f"--{boundary}\r\nContent-Type: message/rfc822\r\n\r\n").encode() + raw + f"\r\n--{boundary}--\r\n".encode()
        headers = {**self._headers, "Content-Type": f"multipart/related; boundary={boundary}"}
        r = self._client.request(method, UPLOAD + path, params={"uploadType": "multipart"}, headers=headers, content=body, timeout=120)
        return self._handle(r)

    def create_draft(self, raw: bytes, thread_id: str | None) -> dict:
        """Returns the Draft: {"id", "message": {"id", "threadId"}}."""
        meta = {"message": {"threadId": thread_id}} if thread_id else {"message": {}}
        return self._upload("POST", "/drafts", meta, raw)

    def update_draft(self, draft_id: str, raw: bytes, thread_id: str | None) -> dict:
        meta = {"id": draft_id, "message": {"threadId": thread_id} if thread_id else {}}
        return self._upload("PUT", f"/drafts/{draft_id}", meta, raw)

    def get_draft_raw(self, draft_id: str) -> tuple[bytes, str | None]:
        """The draft's whole message (RFC 822 bytes) and its thread id."""
        d = self._call("GET", f"/drafts/{draft_id}", params={"format": "raw"})
        raw = d.get("message", {}).get("raw", "")
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), d.get("message", {}).get("threadId")

    def get_draft_meta(self, draft_id: str) -> dict:
        return self._call("GET", f"/drafts/{draft_id}", params={"format": "metadata"})

    def list_drafts(self, limit: int = 25) -> list[dict]:
        return self._call("GET", "/drafts", params={"maxResults": limit}).get("drafts", [])

    def delete_draft(self, draft_id: str) -> None:
        """Discards a draft (the user's own unsent text; Gmail has no trash for drafts)."""
        self._call("DELETE", f"/drafts/{draft_id}")

    def send_draft(self, draft_id: str) -> dict:
        """Sends it; returns the sent Message ({"id", "threadId", "labelIds"})."""
        return self._call("POST", "/drafts/send", json={"id": draft_id})

    def start_watch(self, topic: str) -> Watch:
        w = self._call("POST", "/watch", json={"topicName": topic, "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"})
        return Watch(cursor=int(w["historyId"]), expires_at_ms=int(w["expiration"]))

    def stop_watch(self) -> None:
        self._call("POST", "/stop")
