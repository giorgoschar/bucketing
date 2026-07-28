from fastapi.templating import Jinja2Templates
from pathlib import Path

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------

def format_currency(amount, currency="EUR") -> str:
    symbols = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}
    symbol = symbols.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"


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


templates.env.filters["currency"] = format_currency
templates.env.filters["dmy"] = dmy
templates.env.filters["dmy_short"] = dmy_short
templates.env.filters["initials"] = initials
