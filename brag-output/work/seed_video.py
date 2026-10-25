"""Fictional data for the launch video, on the THROWAWAY test database (port 5433) only.
Writes the sign-in password to video-cred.txt (work folder, never committed)."""
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = "postgresql+psycopg://sift@localhost:5433/sift"
sys.path.insert(0, r"D:\inbox-app\backend")

from sqlalchemy import delete, select  # noqa: E402

from app import starter  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app import crypto, user_settings  # noqa: E402
from app.models import Folder, FolderItem, GmailAccount, LlmCredential, Message, Opportunity, OpportunityEvent, User  # noqa: E402
from app.security import hash_password  # noqa: E402

EMAIL = "video@sift.test"
now = datetime.now(UTC).replace(second=0, microsecond=0)
ago = lambda h: now - timedelta(hours=h)  # noqa: E731
tonight = datetime.now().astimezone().replace(hour=23, minute=59, second=0, microsecond=0).astimezone(UTC)

with get_sessionmaker()() as db:
    old = db.scalar(select(User).where(User.email == EMAIL))
    if old:
        db.delete(old)
        db.commit()
    pw = secrets.token_urlsafe(14)
    u = User(email=EMAIL, password_hash=hash_password(pw))
    db.add(u)
    db.flush()
    personal = GmailAccount(user_id=u.id, email="you@personal.sift.test", label="Personal", color="#e8c547", status="active",
                            last_check_ok_at=now, scopes=["https://www.googleapis.com/auth/gmail.modify"])
    college = GmailAccount(user_id=u.id, email="you@college.sift.test", label="College", color="#6ea8ff", status="active",
                           last_check_ok_at=now, scopes=["https://www.googleapis.com/auth/gmail.modify"])
    db.add_all([personal, college])
    db.flush()
    # AI shows as on (a placeholder key record; nothing in the capture calls the AI)
    db.add(LlmCredential(user_id=u.id, provider="gemini", model="gemini-2.5-flash", encrypted_api_key=crypto.encrypt("placeholder"),
                         key_last4="a91f", status="valid"))
    user_settings.update(db, u.id, {"sender_name": "You"})
    from app.models import Setting
    row = db.scalar(select(Setting).where(Setting.user_id == u.id, Setting.account_id.is_(None)))
    row.data = {**row.data, "grouping_enabled": "no"}

    acme = Opportunity(user_id=u.id, company="Acme Corp", aliases=[], domains=[], deadline=tonight)
    globex = Opportunity(user_id=u.id, company="Globex", aliases=[], domains=[])
    db.add_all([acme, globex])
    db.flush()

    def mail(acc, gid, sender_name, sender, subject, hours, priority, category, *, summary=None, company=None, opp=None,
             deadline=None, unread=True, status="processed", platform=None):
        ext = {"source": "llm"}
        if summary: ext["summary"] = summary
        if company: ext["company"] = company
        if opp: ext["opportunity_id"] = str(opp.id)
        if deadline: ext["deadline"] = deadline.isoformat()
        if platform: ext["platform"] = platform
        m = Message(user_id=u.id, account_id=acc.id, gmail_id=gid, thread_id="t-" + gid, sender=sender, sender_name=sender_name,
                    subject=subject, snippet=summary or subject, received_at=ago(hours), priority=priority, category=category,
                    status=status, labels=["INBOX"] + (["UNREAD"] if unread else []), extraction=ext)
        db.add(m)
        return m

    test = mail(college, "v1", "AssessHub", "noreply@assesshub.example", "Acme Corp online assessment: link inside", 0.4, "urgent",
                "assessment_link", summary="Acme Corp online test, closes tonight 11:59 PM", company="Acme Corp", opp=acme,
                deadline=tonight, platform="AssessHub")
    fraud = mail(personal, "v2", "Northbank", "alerts@northbank.example", "Card blocked due to suspicious activity", 0.9, "urgent",
                 "action_needed", summary="Card blocked after a ₹18,500 attempt. Call the bank if it wasn't you")
    drive = mail(college, "v3", "Placement Cell", "placement@college.example", "Globex campus drive: register by Friday", 2, "normal",
                 "placement_announcement", summary="Globex campus drive, register by Friday 6 PM", company="Globex", opp=globex)
    riya = mail(personal, "v4", "Riya at Globex", "riya@globex.example", "Backend role at Globex: quick chat?", 3, "normal",
                "recruiter", summary="Riya wants a 15-minute call about the backend role", company="Globex", opp=globex)
    acme_drive = mail(college, "v5", "Placement Cell", "placement@college.example", "Acme Corp campus drive announced", 50, "normal",
                      "placement_announcement", summary="Acme Corp campus drive, roles and dates", company="Acme Corp", opp=acme, unread=False)
    weekly = mail(college, "v6", "Campus Weekly", "news@college.example", "This week on campus", 6, "digest", "fyi",
                  summary="Fest dates, library hours, hostel notice", unread=False)
    # bank noise: stored and searchable, never notified
    for i, amt in enumerate(["240.00", "1,180.00", "85.00"]):
        mail(personal, f"vb{i}", "Northbank", "alerts@northbank.example", f"₹{amt} debited from your account via UPI", 1.2 + i,
             "silent", "fyi", status="silenced", unread=False)
    db.flush()

    # company timeline: two mails, a step added by hand, and an upcoming interview
    db.add_all([
        OpportunityEvent(opportunity_id=acme.id, message_id=acme_drive.id, kind="announcement", matched_by="name", occurred_at=acme_drive.received_at,
                         details={"summary": "Acme Corp campus drive announced"}),
        OpportunityEvent(opportunity_id=acme.id, kind="registration", matched_by="user", occurred_at=ago(30),
                         details={"title": "Registered on the portal", "note": "Roll number login", "remind": False}),
        OpportunityEvent(opportunity_id=acme.id, message_id=test.id, kind="assessment", matched_by="ai", occurred_at=test.received_at,
                         details={"summary": "Online test, closes tonight 11:59 PM", "platform": "AssessHub",
                                  "deadline": (tonight).isoformat(),
                                  "links": [{"url": "https://assess.example/t/1", "label": "Start test"}]}),
        OpportunityEvent(opportunity_id=acme.id, kind="interview", matched_by="user", occurred_at=now + timedelta(days=3, hours=4),
                         details={"title": "Technical interview, round 2", "note": "Room 204, two CV copies", "remind": True,
                                  "deadline": (now + timedelta(days=3, hours=4)).isoformat()}),
        OpportunityEvent(opportunity_id=globex.id, message_id=drive.id, kind="announcement", matched_by="name", occurred_at=drive.received_at,
                         details={"summary": "Globex campus drive, register by Friday"}),
        OpportunityEvent(opportunity_id=globex.id, message_id=riya.id, kind="update", matched_by="ai", occurred_at=riya.received_at,
                         details={"summary": "Recruiter call about the backend role"}),
    ])

    # Placements folder (starter setup) with company subfolders holding the mail
    starter.setup(db, u)
    places = db.scalar(select(Folder).where(Folder.user_id == u.id, Folder.name == "Placements"))
    sub = {}
    for name, color in (("Acme Corp", "#c8ff3d"), ("Globex", "#6ea8ff")):
        f = Folder(user_id=u.id, parent_id=places.id, name=name, color=color, position=len(sub))
        db.add(f)
        db.flush()
        sub[name] = f
    for m, f in ((test, "Acme Corp"), (acme_drive, "Acme Corp"), (drive, "Globex"), (riya, "Globex")):
        db.add(FolderItem(folder_id=sub[f].id, account_id=m.account_id, thread_id=m.thread_id))
    db.commit()
    open(r"D:\inbox-app\brag-output\work\video-cred.txt", "w").write(f"{EMAIL}\n{pw}\n")
    print("seeded", u.id, "acme", acme.id, "test mail", test.id, "fraud", fraud.id, "weekly", weekly.id)
