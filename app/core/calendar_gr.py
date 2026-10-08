"""Greek business days: Monday to Friday, minus Greek public holidays.

Pure date arithmetic with no database access (spec §3.2). Orthodox Easter
comes from dateutil. Only the national holidays the household's pay dates
move around are listed; regional saints' days are not.
"""

import calendar
from datetime import date, timedelta
from functools import lru_cache

from dateutil.easter import EASTER_ORTHODOX, easter

# (month, day): New Year, Epiphany, 25 March, Labour Day, Assumption,
# Ochi Day, Christmas, Synaxis of the Theotokos.
FIXED_HOLIDAYS = ((1, 1), (1, 6), (3, 25), (5, 1), (8, 15), (10, 28), (12, 25), (12, 26))
# Days from Orthodox Easter Sunday: Clean Monday, Good Friday, Easter Monday,
# Whit Monday.
EASTER_HOLIDAY_OFFSETS = (-48, -2, 1, 50)

PREVIOUS_BUSINESS_DAY = "previous_business_day"
NEXT_BUSINESS_DAY = "next_business_day"


def orthodox_easter(year: int) -> date:
    """Orthodox Easter Sunday of ``year``."""
    return easter(year, EASTER_ORTHODOX)


@lru_cache(maxsize=64)
def greek_holidays(year: int) -> frozenset[date]:
    """The public holidays of ``year`` that are not business days."""
    sunday = orthodox_easter(year)
    fixed = {date(year, m, d) for m, d in FIXED_HOLIDAYS}
    moving = {sunday + timedelta(days=n) for n in EASTER_HOLIDAY_OFFSETS}
    return frozenset(fixed | moving)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in greek_holidays(d.year)


def previous_business_day(d: date) -> date:
    """``d`` if it is a business day, else the closest business day before it."""
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def next_business_day(d: date) -> date:
    """``d`` if it is a business day, else the closest business day after it."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def adjust_date(d: date, how: str) -> date:
    """Apply a rule's ``adjust``: "none", "previous_business_day" or "next_business_day"."""
    if how == PREVIOUS_BUSINESS_DAY:
        return previous_business_day(d)
    if how == NEXT_BUSINESS_DAY:
        return next_business_day(d)
    return d


def last_business_day(year: int, month: int) -> date:
    """The last business day of the month."""
    return previous_business_day(date(year, month, calendar.monthrange(year, month)[1]))
