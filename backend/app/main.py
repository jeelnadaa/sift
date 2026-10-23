import logging

from fastapi import FastAPI

from app.api import accounts, dev, devices, health, webhooks
from app.config import get_settings

logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Sift API", version="0.1.0")
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(accounts.router)
app.include_router(devices.router)
app.include_router(dev.router)
