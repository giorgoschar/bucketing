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
from slowapi import Limiter
from starlette.requests import Request

from app.config import settings


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
