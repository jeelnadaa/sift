"""Admin commands: python -m app.cli <command>

  create-user EMAIL       create the owner account (Phase 0 bootstrap)
  gen-key                 print a new Fernet key for ENCRYPTION_KEYS
  fake-push EMAIL [HID]   POST a Pub/Sub-shaped push to the local webhook (needs PUBSUB_VERIFY=false)
  connect-url EMAIL       print the Google sign-in link that connects a Gmail account to user EMAIL
  accounts                list connected Gmail accounts and their status
  check                   check every active account for new mail once, now
  set-password EMAIL      set the app sign-in password (asks for it; never shown)
  starter-rules EMAIL     add the starter rule: bank transactions silent, fraud alerts kept
  demo EMAIL              run the sample emails through the pipeline (real notifications)
  demo-clear EMAIL        delete the demo account and its messages
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


def _user(db, email: str):
    from app.models import User

    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        sys.exit(f"no user {email}; run create-user first")
    return user


def set_password(email: str) -> None:
    import getpass

    from app.db import get_sessionmaker
    from app.security import hash_password

    pw = getpass.getpass("New password: ")
    if len(pw) < 8 or pw != getpass.getpass("Repeat: "):
        sys.exit("passwords differ or are shorter than 8 characters")
    with get_sessionmaker()() as db:
        _user(db, email).password_hash = hash_password(pw)
        db.commit()
    print("password set")


def starter_rules(email: str) -> None:
    from app.db import get_sessionmaker
    from app.demo import ensure_starter_rules

    with get_sessionmaker()() as db:
        added = ensure_starter_rules(db, _user(db, email))
        db.commit()
    print(f"added {len(added)} rule(s)" if added else "starter rule already present")


def demo(email: str) -> None:
    from app.db import get_sessionmaker
    from app.demo import DemoProvider, demo_account, ensure_starter_rules, samples
    from app.llm.service import ai_enabled
    from app.pipeline import process_message

    msgs = samples()
    provider = DemoProvider(msgs)
    with get_sessionmaker()() as db:
        user = _user(db, email)
        ensure_starter_rules(db, user)
        account = demo_account(db, user)
        db.commit()
        print(f"AI is {'on' if ai_enabled(db, user.id) else 'off (no valid key)'}")
        print()
        for m in msgs:
            subject = next(h["value"] for h in m["payload"]["headers"] if h["name"] == "Subject")
            out = process_message(db, db.get(type(account), account.id), provider, m["id"])
            flags = ", ".join(x for x in ("notified" if out.notified else "", "LLM called" if out.llm_called else "") if x)
            print(f"{out.priority or '-':7} by {out.decided_by:10} {flags:22} {subject}")


def demo_clear(email: str) -> None:
    from app.db import get_sessionmaker
    from app.demo import clear

    with get_sessionmaker()() as db:
        n = clear(db, _user(db, email))
        db.commit()
    print(f"removed demo account and {n} message(s)")


def main(argv: list[str]) -> None:
    commands = {"create-user": create_user, "gen-key": gen_key, "fake-push": fake_push, "connect-url": connect_url, "accounts": accounts, "check": check,
                "set-password": set_password, "starter-rules": starter_rules, "demo": demo, "demo-clear": demo_clear}
    if len(argv) < 1 or argv[0] not in commands:
        print(__doc__)
        sys.exit(1)
    commands[argv[0]](*argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
