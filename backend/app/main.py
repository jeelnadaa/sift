from fastapi import FastAPI

from app import webui
from app.api import (
    accounts,
    assistant,
    attachments,
    auth,
    bulk,
    categories,
    compose,
    dev,
    devices,
    events,
    folders,
    groups,
    health,
    links,
    mail_actions,
    messages,
    opportunities,
    rules,
    saved,
    scans,
    search,
    senders,
    settings,
    templates,
    threads,
    todos,
    unsubscribe,
    webhooks,
)
from app.config import get_settings, setup_logging

setup_logging()

docs = get_settings().api_docs
app = FastAPI(title="Sift API", version="0.2.0", docs_url="/docs" if docs else None, redoc_url=None, openapi_url="/openapi.json" if docs else None)
for module in (health, webhooks, auth, accounts, assistant, attachments, messages, folders, groups, opportunities, todos, rules, scans, categories, senders, settings, templates, threads, unsubscribe, devices, links, mail_actions, bulk, compose, events, saved, search, dev):
    app.include_router(module.router)
webui.mount(app)

_slow = get_settings().dev_slow_ms if get_settings().env != "prod" else 0
if _slow > 0:
    import asyncio

    @app.middleware("http")
    async def _dev_slow(request, call_next):  # DEV_SLOW_MS: imitate a slow connection (never in prod)
        if request.url.path.startswith("/api/v1/") and not request.url.path.startswith("/api/v1/events"):
            await asyncio.sleep(_slow / 1000)
        return await call_next(request)
