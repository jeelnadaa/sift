from fastapi import FastAPI

from app import webui
from app.api import (
    accounts,
    assistant,
    attachments,
    auth,
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
for module in (health, webhooks, auth, accounts, assistant, attachments, messages, folders, groups, opportunities, todos, rules, scans, categories, senders, settings, templates, threads, unsubscribe, devices, links, mail_actions, compose, events, saved, search, dev):
    app.include_router(module.router)
webui.mount(app)
