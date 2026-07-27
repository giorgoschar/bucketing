"""
/api/v1 — JSON REST API for mobile and external clients.
All routes use JWT Bearer auth (see app/api_auth.py).
The existing HTML routes are completely untouched.
"""
from fastapi import APIRouter

from app.routes.api import auth, dashboard, transactions, buckets, bills, income, insights, notifications, settings

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(transactions.router)
router.include_router(buckets.router)
# Household-wide settle up (defined alongside buckets, mounted at /settlement)
router.include_router(buckets._household_router)
router.include_router(bills.router)
router.include_router(income.router)
router.include_router(insights.router)
router.include_router(notifications.router)
router.include_router(settings.router)
