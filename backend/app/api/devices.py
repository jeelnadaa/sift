import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import notify
from app.db import get_db
from app.models import Device, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


class DeviceIn(BaseModel):
    fcm_token: str = Field(min_length=10)
    platform: str = "android"
    label: str | None = None


@router.post("/devices", status_code=201)
def register_device(body: DeviceIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    stmt = insert(Device).values(user_id=user.id, fcm_token=body.fcm_token, platform=body.platform, label=body.label, last_seen_at=now)
    stmt = stmt.on_conflict_do_update(index_elements=["fcm_token"], set_={"user_id": user.id, "label": body.label, "last_seen_at": now}).returning(Device.id)
    device_id = db.execute(stmt).scalar_one()
    db.commit()
    return {"id": str(device_id)}


@router.post("/notifications/{notification_id}/ack", status_code=204)
def acknowledge(notification_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """The app calls this when a notification reaches the phone; urgent ones are re-sent until it does."""
    if not notify.acknowledge(db, user.id, notification_id):
        raise HTTPException(404, "notification not found")
    db.commit()
