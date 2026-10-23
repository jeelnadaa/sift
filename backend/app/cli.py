"""Admin commands: python -m app.cli <command>

  create-user EMAIL       create the owner account (Phase 0 bootstrap)
  gen-key                 print a new Fernet key for ENCRYPTION_KEYS
  fake-push EMAIL [HID]   POST a Pub/Sub-shaped push to the local webhook (needs PUBSUB_VERIFY=false)
"""
import base64
import json
import sys

from sqlalchemy import select


def create_user(email: str) -> None:
    from app.db import get_sessionmaker
    from app.models import User

    with get_sessionmaker()() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            print("user exists")
            return
        db.add(User(email=email.lower()))
        db.commit()
    print("created", email.lower())


def gen_key() -> None:
    from cryptography.fernet import Fernet

    print(Fernet.generate_key().decode())


def fake_push(email: str, history_id: str = "1000", url: str = "http://localhost:8000/webhooks/gmail") -> None:
    import httpx

    data = base64.urlsafe_b64encode(json.dumps({"emailAddress": email, "historyId": int(history_id)}).encode()).decode()
    body = {"message": {"data": data, "messageId": f"fake-{history_id}", "publishTime": "2026-01-01T00:00:00Z"}, "subscription": "projects/local/subscriptions/fake"}
    r = httpx.post(url, json=body, timeout=10)
    print(r.status_code)


def main(argv: list[str]) -> None:
    commands = {"create-user": create_user, "gen-key": gen_key, "fake-push": fake_push}
    if len(argv) < 1 or argv[0] not in commands:
        print(__doc__)
        sys.exit(1)
    commands[argv[0]](*argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
