import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app import jobs
from app.config import get_settings
from app.pubsub import PushAuthError, PushPayloadError, parse_gmail_push, verify_push_token

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/gmail", status_code=204)
async def gmail_push(request: Request, authorization: str | None = Header(default=None)) -> Response:
    """Pub/Sub push endpoint. Verify, enqueue, acknowledge fast (brief section 7 step 1)."""
    settings = get_settings()
    if settings.pubsub_verify:
        try:
            verify_push_token(authorization, settings)
        except PushAuthError as exc:
            log.warning("rejected pubsub push: %s", exc)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized") from exc
    elif settings.env == "prod":
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "PUBSUB_VERIFY must be on in prod")

    try:
        push = parse_gmail_push(await request.json())
    except (PushPayloadError, ValueError) as exc:
        # Acknowledge anyway: a malformed message will never parse, and a non-2xx makes Pub/Sub retry forever.
        log.warning("ignored malformed pubsub push: %s", exc)
        return Response(status_code=204)

    payload = {"email": push.email, "history_id": push.history_id, "pubsub_message_id": push.pubsub_message_id}
    dedupe = f"push:{push.pubsub_message_id}" if push.pubsub_message_id else None
    await jobs.enqueue("gmail_push", payload, dedupe_key=dedupe)
    log.info("pubsub push accepted (history %s)", push.history_id)
    return Response(status_code=204)
