from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import settings
from app.database import engine, Base

# Import models so Alembic / create_all picks them up
import app.models  # noqa: F401

from app.routes import auth, dashboard, buckets, transactions, income, bills, settings as settings_router
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

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
