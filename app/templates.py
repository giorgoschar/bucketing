import hashlib
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.auth import form_csrf_token
from app.core.money import quantize, to_decimal
from app.models import PaymentMethod
from app.schemas import OWN_SHARE_CHOICE


class _Templates(Jinja2Templates):
    """Starlette 1.x only accepts TemplateResponse(request, name, context).

    The routes use the older TemplateResponse(name, {"request": request, ...})
    form throughout; this accepts both so the upgrade does not have to touch
    every call site.
    """

    def TemplateResponse(self, *args, **kwargs):  # noqa: N802 — Starlette's name
        if args and isinstance(args[0], str):
            name, *rest = args
            context = rest[0] if rest else kwargs.pop("context", {})
            return super().TemplateResponse(context["request"], name, context, *rest[1:], **kwargs)
        return super().TemplateResponse(*args, **kwargs)


templates = _Templates(directory=str(Path(__file__).parent.parent / "templates"))


STATIC_DIR = Path(__file__).parent.parent / "static"
_asset_hashes: dict[str, tuple[float, str]] = {}


def static_url(path: str) -> str:
    """/static/<path>?v=<content hash>.

    The service worker serves /static/ cache-first while pages come from the
    network, so after a deploy new HTML could run against old cached JS
    (Alpine then fails on functions the old file lacks). A content-hashed URL
    is a different cache key, so a page always gets the JS it was built with.
    """
    file = STATIC_DIR / path
    try:
        mtime = file.stat().st_mtime
    except OSError:
        return f"/static/{path}"
    cached = _asset_hashes.get(path)
    if cached is None or cached[0] != mtime:
        digest = hashlib.sha256(file.read_bytes()).hexdigest()[:10]
        cached = _asset_hashes[path] = (mtime, digest)
    return f"/static/{path}?v={cached[1]}"


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


def dt(value) -> str:
    """Date + time, e.g. 08/10/2026 14:35 — for logs and recent-attempt tails."""
    if not value:
        return ""
    return value.strftime("%d/%m/%Y %H:%M")


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
templates.env.globals["static_url"] = static_url
templates.env.globals["payment_methods"] = list(PaymentMethod)
# Payer dropdown value for "Each paid their own share" (see app.schemas).
templates.env.globals["OWN_SHARE_CHOICE"] = OWN_SHARE_CHOICE
templates.env.filters["currency"] = format_currency
templates.env.filters["dmy"] = dmy
templates.env.filters["dmy_short"] = dmy_short
templates.env.filters["dt"] = dt
templates.env.filters["initials"] = initials
templates.env.filters["plain_number"] = plain_number
templates.env.filters["litres"] = litres
templates.env.filters["per_litre"] = per_litre
