from fastapi import FastAPI

from app.api import accounts, auth, dev, devices, health, messages, rules, settings, webhooks
from app.config import get_settings, setup_logging

setup_logging()

docs = get_settings().api_docs
app = FastAPI(title="Sift API", version="0.2.0", docs_url="/docs" if docs else None, redoc_url=None, openapi_url="/openapi.json" if docs else None)
for module in (health, webhooks, auth, accounts, messages, rules, settings, devices, dev):
    app.include_router(module.router)
