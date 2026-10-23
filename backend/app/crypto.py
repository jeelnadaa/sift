"""Encryption at rest for Gmail refresh tokens and users' LLM API keys.

ENCRYPTION_KEYS holds one or more Fernet keys, newest first. Encrypt uses the
newest; decrypt tries all, so keys can be rotated without downtime.
Generate a key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in get_settings().encryption_keys.split(",") if k.strip()]
    if not keys:
        raise EncryptionNotConfigured("Set ENCRYPTION_KEYS before storing secrets")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
