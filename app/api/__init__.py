"""
/api/v1 — JSON REST API for mobile and external clients.
All routes use JWT Bearer auth (see app/api_auth.py).
The existing HTML routes are completely untouched.
"""

from fastapi import APIRouter

from app.api import (
    auth,
    bills,
    buckets,
    bulk,
    cash,
    dashboard,
    income,
    ingest,
    insights,
    matches,
    notifications,
    personal_tokens,
    plan,
    recurring,
    settings,
    stock,
    transactions,
)

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(bulk.router)  # before transactions: /transactions/bulk is not a txn id
router.include_router(transactions.router)
router.include_router(buckets.router)
# Household-wide settle up (defined alongside buckets, mounted at /settlement)
router.include_router(buckets._household_router)
router.include_router(bills.router)
router.include_router(cash.router)
router.include_router(income.router)
router.include_router(ingest.router)
router.include_router(insights.router)
router.include_router(notifications.router)
router.include_router(personal_tokens.router)
router.include_router(settings.router)
router.include_router(stock.router)
router.include_router(stock.products_router)

# Planning (spec §6.3)
router.include_router(recurring.router)
router.include_router(matches.router)
router.include_router(plan.router)
