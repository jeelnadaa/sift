"""Admin commands: python -m app.cli <command>

  create-user EMAIL       create the owner account (Phase 0 bootstrap)
  gen-key                 print a new Fernet key for ENCRYPTION_KEYS
  fake-push EMAIL [HID]   POST a Pub/Sub-shaped push to the local webhook (needs PUBSUB_VERIFY=false)
  connect-url EMAIL       print the Google sign-in link that connects a Gmail account to user EMAIL
  accounts                list connected Gmail accounts and their status
  check                   check every active account for new mail once, now
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


def connect_url(email: str) -> None:
    from app.mail.google_oauth import authorization_url, redirect_uri

    print(f"Redirect URI (must be registered on the OAuth client): {redirect_uri()}")
    print()
    print(authorization_url(email.lower()))


def accounts() -> None:
    from app.db import get_sessionmaker
    from app.models import GmailAccount

    with get_sessionmaker()() as db:
        for a in db.scalars(select(GmailAccount).order_by(GmailAccount.created_at)):
            print(f"{a.email:40} {a.status:16} history={a.history_id} {a.status_detail or ''}")


def check() -> None:
    from app.accounts import active_account_ids, check_account
    from app.db import get_sessionmaker

    with get_sessionmaker()() as db:
        ids = active_account_ids(db)
    for account_id in ids:
        print(account_id, check_account(account_id), "new")


def main(argv: list[str]) -> None:
    commands = {"create-user": create_user, "gen-key": gen_key, "fake-push": fake_push, "connect-url": connect_url, "accounts": accounts, "check": check}
    if len(argv) < 1 or argv[0] not in commands:
        print(__doc__)
        sys.exit(1)
    commands[argv[0]](*argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
