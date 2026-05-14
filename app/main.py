from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import engine, Base

# Import models so Alembic / create_all picks them up
import app.models  # noqa: F401

from app.routes import auth, dashboard, buckets, transactions, income, bills, settings as settings_router
from app.scheduler import start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Rate limiter (shared across routers)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
# Security headers middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.tailwindcss.com cdn.jsdelivr.net unpkg.com; "
        "style-src 'self' 'unsafe-inline' cdn.tailwindcss.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
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


@app.get("/health", include_in_schema=False)
def health_check():
    return JSONResponse({"status": "ok"})
