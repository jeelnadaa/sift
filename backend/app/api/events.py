"""Live updates for open web pages: GET /api/v1/events (server-sent events).

Sends "data: {json}" for each change of the signed-in user (see app/events.py), a comment every
20 s so proxies and Cloudflare keep the connection open, and ends when the page goes away.
The page reconnects on its own; after a reconnect it reloads, so nothing is missed.
"""
import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.events import hub
from app.security import user_id_from_header

router = APIRouter(prefix="/api/v1")
MAX_STREAMS_PER_USER = 12
PING_SECONDS = 20


@router.get("/events")
async def stream(request: Request, user_id: uuid.UUID = Depends(user_id_from_header)) -> StreamingResponse:
    key = str(user_id)
    if hub.count(key) >= MAX_STREAMS_PER_USER:
        raise HTTPException(429, "too many open tabs")
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    hub.subscribe(key, loop, q)

    async def events():
        try:
            yield "retry: 3000\n\n"
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=PING_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            hub.unsubscribe(key, loop, q)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
