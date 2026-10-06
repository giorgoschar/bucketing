"""
Money arithmetic helpers.

Amounts are ``Decimal`` from the database through to the template or JSON
response. Python's ``round()`` uses banker's rounding on binary floats
(``round(0.125, 2) == 0.12``, ``round(2.675, 2) == 2.67``), which is not how
anyone expects a currency figure to round; everything here rounds half up.
"""

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
TENTH = Decimal("0.1")


def to_decimal(value) -> Decimal:
    """Coerce a DB value, float, int or numeric string to ``Decimal``.

    Floats go through ``str`` so 0.1 becomes Decimal("0.1"), not its binary
    expansion. ``None`` is zero.
    """
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def quantize(value, exp: Decimal = CENT) -> Decimal:
    """Round to 2 decimal places (or ``exp``), half up."""
    return to_decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def percent(part, whole) -> Decimal:
    """``part / whole * 100`` rounded half up to one decimal place.

    Returns zero when ``whole`` is zero.
    """
    whole = to_decimal(whole)
    if not whole:
        return quantize(ZERO, TENTH)
    return quantize(to_decimal(part) / whole * 100, TENTH)
