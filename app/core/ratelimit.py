"""
Shared rate limiter.

Previously ``app/main.py``, ``app/routes/auth.py`` and ``app/routes/settings.py``
each constructed their own ``Limiter``. Each instance carries its own in-memory
counter store, so the login limit registered on one was tracked independently of
the one registered as ``app.state.limiter`` — quietly multiplying the effective
allowance. One instance, imported everywhere, keeps the budgets honest.

Note on deployment: the default storage is per-process memory, and
``entrypoint.sh`` runs ``uvicorn --workers 2``, so a limit of "5 per 15 minutes"
is really "5 per worker". Point ``RATE_LIMIT_STORAGE_URI`` at Redis
(e.g. ``redis://localhost:6379``) to enforce limits across workers.
"""

import hashlib

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings


def client_key(request: Request) -> str:
    """Rate-limit bucket key.

    Behind a reverse proxy every request carries the proxy's IP, which would put
    all users in one bucket and let a single attacker lock everyone out. When
    TRUST_PROXY_HEADERS is set we key off the forwarded client IP instead.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(
    key_func=client_key,
    storage_uri=settings.rate_limit_storage_uri or None,
)


def ingest_token_key(request: Request) -> str:
    """Rate-limit key for the ingest endpoint: one bucket per personal token.

    Keyed on the SHA-256 of the bearer token (never the token itself, so the
    plaintext does not sit in the limiter's storage). Falls back to the client
    IP when there is no bearer token; such requests are rejected with 401
    before the limit is checked anyway.
    """
    auth = request.headers.get("Authorization", "")
    scheme, _, credentials = auth.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return "pat:" + hashlib.sha256(credentials.strip().encode()).hexdigest()
    return client_key(request)
