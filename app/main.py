import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

# Import models so Alembic / create_all picks them up
import app.models  # noqa: F401
from app import web_app
from app.api import router as api_router
from app.auth import COOKIE_NAME, CSRF_COOKIE_NAME, PENDING_COOKIE_NAME, CSRFError
from app.core.config import settings
from app.core.database import Base, engine
from app.core.ratelimit import limiter  # single shared instance
from app.routes import (
    auth,
    automations,
    bills,
    buckets,
    cash,
    dashboard,
    income,
    scan,
    transactions,
    transactions_search,
)
from app.routes import insights as insights_router
from app.routes import notifications as notifications_router
from app.routes import settings as settings_router
from app.routes import settlement as settlement_router
from app.routes import stock as stock_router
from app.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


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

# Authlib keeps the OIDC state, nonce and PKCE verifier here between /app/auth/login
# and the callback. Lax, because the callback is a cross-site top-level redirect.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    session_cookie="oidc_tx",
    max_age=600,
    path="/app/auth",
    same_site="lax",
    https_only=not settings.debug,
)

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
    # Only require_auth sets request.state.user, after checking session_version
    # and membership — a merely well-signed cookie gets nothing.
    if not request.cookies.get(CSRF_COOKIE_NAME) and request.cookies.get(COOKIE_NAME):
        from app.auth import generate_csrf_token

        authed_user = getattr(request.state, "user", None)
        if authed_user is not None:
            csrf_val = generate_csrf_token(authed_user.id)
            response.set_cookie(
                CSRF_COOKIE_NAME,
                csrf_val,
                httponly=False,
                samesite="strict",
                max_age=settings.session_max_age_seconds,
                secure=not settings.debug,
            )
    pre_nonce = getattr(request.state, "pre_csrf_nonce", None)
    if pre_nonce:
        from app.auth import set_pre_csrf_cookie

        set_pre_csrf_cookie(response, pre_nonce)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Tailwind is a local stylesheet now, so cdn.tailwindcss.com is gone from
    # every directive, and the receipt-scanner libraries (qr-scanner,
    # tesseract.js, pdf.js) are vendored under /static/vendor, so no CDN either.
    # 'unsafe-eval' stays because Alpine compiles its expressions with
    # new Function(); it also covers WebAssembly compilation for tesseract's
    # core, so 'wasm-unsafe-eval' is not needed.
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        response.headers["Content-Security-Policy"] = web_app.APP_CSP
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "worker-src blob: 'self'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' blob:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
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
app.include_router(web_app.router)
app.include_router(web_app.spa)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(buckets.router)
app.include_router(transactions.router)
app.include_router(scan.router)
app.include_router(transactions_search.router)
app.include_router(income.router)
app.include_router(bills.router)
app.include_router(automations.router)
app.include_router(settings_router.router)
app.include_router(notifications_router.router)
app.include_router(insights_router.router)
app.include_router(settlement_router.router)
app.include_router(cash.router)
app.include_router(stock_router.router)
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
