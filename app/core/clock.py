"""The single source of "now" and "today" for the app.

All DateTime columns are timezone-naive and store UTC: use ``utcnow_naive()``
for anything written to or compared against them. ``utcnow()`` (aware) is for
code that works with aware values (JWT claims, etc.). "What day is it for the
household" is ``local_today()``, which honours ``APP_TIMEZONE``.
"""
import logging
from datetime import UTC, date, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


def tz() -> tzinfo:
    """The household calendar timezone, falling back to UTC if misconfigured."""
    from app.core.config import settings
    try:
        return ZoneInfo(settings.app_timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning("Unknown APP_TIMEZONE %r — falling back to UTC",
                       settings.app_timezone)
        return UTC


def utcnow() -> datetime:
    """Timezone-aware UTC now. The one underlying clock; tests patch this."""
    return datetime.now(UTC)


def utcnow_naive() -> datetime:
    """Naive UTC now, for the app's timezone-naive DateTime columns."""
    return utcnow().replace(tzinfo=None)


def local_today() -> date:
    """Today's date on the household's calendar (APP_TIMEZONE)."""
    return utcnow().astimezone(tz()).date()
