from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.auth import form_csrf_token
from app.models import PaymentMethod
from app.money import quantize, to_decimal
from app.schemas import OWN_SHARE_CHOICE

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------

def format_currency(amount, currency="EUR") -> str:
    symbols = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}
    symbol = symbols.get(currency, currency + " ")
    # Round half up first: f"{0.125:,.2f}" alone gives "0.12".
    return f"{symbol}{quantize(amount or 0):,.2f}"


def dmy(value, with_year: bool = True) -> str:
    """Day-first date, the convention in Greece and most of Europe.

    Dates were rendered with month abbreviations ("15 Aug 2026"), which reads
    as an anglophone format. This gives 15/08/2026.
    """
    if not value:
        return ""
    return value.strftime("%d/%m/%Y" if with_year else "%d/%m")


def dmy_short(value) -> str:
    return dmy(value, with_year=False)


def initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def plain_number(value) -> str:
    """A Decimal without trailing zeros or exponent, for a form field's
    value: 1.7890 -> "1.789", 100 -> "100". None is blank."""
    if value is None:
        return ""
    return f"{to_decimal(value).normalize():f}"


def litres(value) -> str:
    """Fuel litres for display: 33.538 -> "33.54 L"."""
    return f"{quantize(value or 0):,.2f} L"


def per_litre(value, currency="EUR") -> str:
    """A fuel price for display, to the tenth of a cent: "€1.789/L"."""
    symbol = format_currency(0, currency).removesuffix("0.00")
    return f"{symbol}{quantize(value or 0, Decimal('0.001'))}/L"


templates.env.globals["form_csrf_token"] = form_csrf_token
templates.env.globals["payment_methods"] = list(PaymentMethod)
# Payer dropdown value for "Each paid their own share" (see app.schemas).
templates.env.globals["OWN_SHARE_CHOICE"] = OWN_SHARE_CHOICE
templates.env.filters["currency"] = format_currency
templates.env.filters["dmy"] = dmy
templates.env.filters["dmy_short"] = dmy_short
templates.env.filters["initials"] = initials
templates.env.filters["plain_number"] = plain_number
templates.env.filters["litres"] = litres
templates.env.filters["per_litre"] = per_litre
