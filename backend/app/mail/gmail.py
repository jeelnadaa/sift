"""Gmail implementation of MailProvider, over the Gmail REST API with httpx.

Quota (per user, per minute: 6,000 units): history.list = 2, messages.get = 20 (metadata) or 60 (full),
watch = 100. Polling every 5 s costs 24 units per account per minute.
"""
import httpx

from app.mail.base import AuthRevoked, Changes, CursorExpired, Profile, Watch
from app.mail.message import METADATA_HEADERS

API = "https://gmail.googleapis.com/gmail/v1/users/me"
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
        r = self._client.request(method, API + path, headers=self._headers, **kw)
        if r.status_code == 200:
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
        labels: list[tuple[str, list[str], list[str]]] = []
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
                    labels = set(m.get("labelIds", []))
                    if m["id"] in seen or (labels & SKIP_LABELS and "INBOX" not in labels):
                        continue
                    seen.add(m["id"])
                    ids.append(m["id"])
                for change in h.get("labelsAdded", []):
                    labels.append((change["message"]["id"], change.get("labelIds", []), []))
                for change in h.get("labelsRemoved", []):
                    labels.append((change["message"]["id"], [], change.get("labelIds", [])))
            token = page.get("nextPageToken")
            if not token:
                return Changes(message_ids=ids, cursor=cursor, label_changes=labels)
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

    def get_metadata(self, message_id: str) -> dict:
        """Headers only (20 quota units). Never fetches the body."""
        params = [("format", "metadata")] + [("metadataHeaders", h) for h in METADATA_HEADERS]
        return self._call("GET", f"/messages/{message_id}", params=params)

    def get_full(self, message_id: str) -> dict:
        """Full message incl. body parts (60 units). Only when a rule or the LLM needs the body."""
        return self._call("GET", f"/messages/{message_id}", params={"format": "full"})

    def start_watch(self, topic: str) -> Watch:
        w = self._call("POST", "/watch", json={"topicName": topic, "labelIds": ["INBOX"], "labelFilterBehavior": "INCLUDE"})
        return Watch(cursor=int(w["historyId"]), expires_at_ms=int(w["expiration"]))

    def stop_watch(self) -> None:
        self._call("POST", "/stop")
