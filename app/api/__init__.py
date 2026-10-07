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
    cash,
    category_rules,
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
# 2d §7.4: owned here, consumed by 2b's composer.
router.include_router(category_rules.router)
router.include_router(stock.router)
router.include_router(stock.products_router)

# Planning (spec §6.3)
router.include_router(recurring.router)
router.include_router(matches.router)
router.include_router(plan.router)
