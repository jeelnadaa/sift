from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import get_db
from app.models import Device, User

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_admin)])


class DeviceIn(BaseModel):
    user_email: str  # Phase 0 only; Phase 1 takes the user from the JWT
    fcm_token: str = Field(min_length=10)
    platform: str = "android"
    label: str | None = None


@router.post("/devices", status_code=201)
def register_device(body: DeviceIn, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.user_email.lower()))
    if user is None:
        raise HTTPException(404, "unknown user")
    stmt = insert(Device).values(user_id=user.id, fcm_token=body.fcm_token, platform=body.platform, label=body.label, last_seen_at=datetime.now(UTC))
    stmt = stmt.on_conflict_do_update(
        index_elements=["fcm_token"],
        set_={"user_id": user.id, "label": body.label, "last_seen_at": datetime.now(UTC)},
    ).returning(Device.id)
    device_id = db.execute(stmt).scalar_one()
    db.commit()
    return {"id": str(device_id)}
