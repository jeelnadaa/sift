"""Failed sign-in throttling (in memory, per API process).

Keys are the email and the client address. Behind Cloudflare Tunnel every request comes from
localhost, so the visitor address is taken from CF-Connecting-IP when present.
"""
import time
from collections import defaultdict, deque

from fastapi import Request

WINDOW = 15 * 60
_failures: dict[str, deque[float]] = defaultdict(deque)


def client_address(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def _recent(key: str, now: float) -> deque[float]:
    q = _failures[key]
    while q and q[0] < now - WINDOW:
        q.popleft()
    return q


def retry_after(keys: list[str], limit: int) -> int:
    """Seconds until another attempt is allowed, or 0."""
    now = time.time()
    waits = [int(q[0] + WINDOW - now) + 1 for k in keys if len(q := _recent(k, now)) >= limit]
    return max(waits, default=0)


def record_failure(keys: list[str]) -> None:
    now = time.time()
    for k in keys:
        _recent(k, now).append(now)


def reset(key: str) -> None:
    _failures.pop(key, None)
