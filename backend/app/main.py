from fastapi import FastAPI

from app.api import accounts, auth, dev, devices, health, messages, rules, settings, webhooks
from app.config import setup_logging

setup_logging()

app = FastAPI(title="Sift API", version="0.2.0")
for module in (health, webhooks, auth, accounts, messages, rules, settings, devices, dev):
    app.include_router(module.router)
