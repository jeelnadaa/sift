"""Throwaway server for the video capture (port 8010, throwaway DB on 5433). The fictional
accounts (*.sift.test) get a stand-in Gmail that returns fictional conversations; nothing here
reaches the network."""
import base64
import os
import sys

os.chdir(r"D:\inbox-app\backend")
sys.path.insert(0, r"D:\inbox-app\backend")
os.environ["DATABASE_URL"] = "postgresql+psycopg://sift@localhost:5433/sift"

from app import accounts as account_service  # noqa: E402


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


BODIES = {
    "v1": ("AssessHub <noreply@assesshub.example>", "Acme Corp online assessment: link inside",
           "Hi,\n\nYour Acme Corp online assessment is ready. It closes tonight at 11:59 PM.\n\nDuration: 60 minutes\nStart test: https://assess.example/t/1\n\nAll the best,\nAssessHub"),
}


class VideoGmail:
    def _msg(self, gid: str) -> dict:
        frm, subj, text = BODIES.get(gid, ("Sift <hello@sift.example>", "Hello", "Hello"))
        return {"id": gid, "threadId": "t-" + gid, "labelIds": ["INBOX"], "snippet": text[:80], "internalDate": "1792900000000",
                "payload": {"mimeType": "text/plain", "headers": [
                    {"name": "From", "value": frm}, {"name": "To", "value": "you@college.sift.test"},
                    {"name": "Subject", "value": subj}, {"name": "Date", "value": "Sun, 25 Oct 2026 07:14:00 +0530"}],
                    "body": {"data": b64(text)}}}

    def get_full(self, gid):
        return self._msg(gid)

    def get_thread(self, tid):
        return {"id": tid, "messages": [self._msg(tid.removeprefix("t-"))]}

    def modify_thread(self, *a):
        pass


real = account_service.provider_for
account_service.provider_for = lambda a: VideoGmail() if a.email.endswith(".sift.test") else real(a)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8010, log_level="warning")
