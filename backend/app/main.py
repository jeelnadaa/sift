import logging

from fastapi import FastAPI

from app.api import accounts, auth, dev, devices, health, messages, rules, settings, webhooks
from app.config import get_settings

logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Sift API", version="0.2.0")
for module in (health, webhooks, auth, accounts, messages, rules, settings, devices, dev):
    app.include_router(module.router)
