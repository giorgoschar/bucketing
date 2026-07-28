from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import engine, Base
from app.auth import CSRFError, COOKIE_NAME, CSRF_COOKIE_NAME, PENDING_COOKIE_NAME

# Import models so Alembic / create_all picks them up
import app.models  # noqa: F401

from app.routes import auth, dashboard, buckets, transactions, income, bills, settings as settings_router
from app.routes import notifications as notifications_router
from app.routes import insights as insights_router
from app.routes import settlement as settlement_router
from app.routes.api import router as api_router
from app.scheduler import start_scheduler, stop_scheduler

import logging

logger = logging.getLogger(__name__)

# Rate limiter — single shared instance (see app/ratelimit.py)
from app.ratelimit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.vapid_private_key or not settings.vapid_public_key:
        logger.warning(
            "VAPID keys are not configured. Push notifications will be silently disabled. "
            "Set VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY environment variables."
        )
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# CORS — required for mobile apps and browser-based SPA clients.
# Configure CORS_ALLOWED_ORIGINS env var with space-separated origins in production.
# In dev, defaults to empty list (same-origin only). Use "*" for local dev if needed.
# ---------------------------------------------------------------------------
if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )


@app.exception_handler(CSRFError)
async def csrf_error_handler(request: Request, exc: CSRFError):
    """On CSRF failure: only wipe session for real browser navigations.
    Return 403 JSON for background fetch/HTMX requests to avoid unexpected logouts."""
    accept = request.headers.get("accept", "")
    is_background = (
        bool(request.headers.get("HX-Request"))
        or "application/json" in accept
        or "text/html" not in accept
    )
    if is_background:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
    response = RedirectResponse(url="/login?expired=1", status_code=302)
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    response.delete_cookie(PENDING_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # If the user has a valid authenticated session but no CSRF cookie (e.g. it was
    # previously wiped by an aggressive error handler), issue a fresh one so that
    # the very next state-changing request will pass CSRF validation again.
    if not request.cookies.get(CSRF_COOKIE_NAME) and request.cookies.get(COOKIE_NAME):
        from app.auth import decode_cookie, generate_csrf_token
        session = decode_cookie(request.cookies.get(COOKIE_NAME))
        if session and session.get("state") == "authenticated":
            csrf_val = generate_csrf_token(session["user_id"])
            response.set_cookie(
                CSRF_COOKIE_NAME, csrf_val,
                httponly=False, samesite="strict",
                max_age=60 * 60 * 24 * 30,
                secure=not settings.debug,
            )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Tailwind is a local stylesheet now, so cdn.tailwindcss.com is gone from
    # every directive. jsdelivr stays: the receipt scanner loads qr-scanner,
    # tesseract.js and pdf.js from it. 'unsafe-eval' stays because Alpine
    # compiles its expressions with new Function().
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "worker-src blob: 'self'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' cdn.jsdelivr.net blob:;"
    )
    if not settings.debug:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# NOTE: /uploads is NOT mounted as a public static route.
# Files are served through the authenticated /files/{filename} route in transactions.

# ---------------------------------------------------------------------------
# Dev-only: auto-create tables (production uses Alembic via entrypoint.sh)
# ---------------------------------------------------------------------------
if settings.debug:
    Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(buckets.router)
app.include_router(transactions.router)
app.include_router(income.router)
app.include_router(bills.router)
app.include_router(settings_router.router)
app.include_router(notifications_router.router)
app.include_router(insights_router.router)
app.include_router(settlement_router.router)
app.include_router(api_router)


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Serve the service worker from the root scope so it can control all pages."""
    sw_path = Path(__file__).parent.parent / "static" / "sw.js"
    return FileResponse(
        str(sw_path),
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.get("/health", include_in_schema=False)
def health_check():
    return JSONResponse({"status": "ok"})
