from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.auth import form_csrf_token
from app.money import quantize

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


templates.env.globals["form_csrf_token"] = form_csrf_token
templates.env.filters["currency"] = format_currency
templates.env.filters["dmy"] = dmy
templates.env.filters["dmy_short"] = dmy_short
templates.env.filters["initials"] = initials
