"""
Fuel expenses: the litres behind an expense in the built-in Fuel category.

The household's category with ``system_key == FUEL_SYSTEM_KEY`` (see app.seed)
unlocks a price per litre on an expense. The litres are always the server's
own amount / price, rounded half up to 3 dp; amount and price are both in the
transaction currency, so the exchange rate does not enter into it.
"""

from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import to_decimal
from app.models import FUEL_SYSTEM_KEY, Category, TransactionType

LITRE = Decimal("0.001")
# Upper bound of transactions.fuel_litres (NUMERIC(10,3)).
MAX_LITRES = Decimal("9999999.999")
TOO_MANY_LITRES = "That price per litre gives an impossible number of litres. Check the price."


def fuel_category_id(db: Session, household_id: str) -> str | None:
    """The id of the household's built-in Fuel category, if it has one."""
    row = (
        db.query(Category.id)
        .filter(Category.household_id == household_id, Category.system_key == FUEL_SYSTEM_KEY)
        .first()
    )
    return row[0] if row else None


def litres_for(amount, price) -> Decimal:
    """``amount / price`` in litres, 3 dp half up."""
    return (to_decimal(amount) / to_decimal(price)).quantize(LITRE, rounding=ROUND_HALF_UP)


def fuel_fields(
    db: Session,
    household_id: str,
    *,
    category_id: str | None,
    txn_type: TransactionType,
    amount,
    price: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """``(fuel_price_per_litre, fuel_litres)`` to store on a transaction.

    Both None unless it is an expense in the Fuel category with a price;
    otherwise the litres are recomputed from the amount (HTTP 400 if they would
    not fit the column, i.e. a mistyped price).
    """
    if (
        price is None
        or txn_type != TransactionType.expense
        or not category_id
        or category_id != fuel_category_id(db, household_id)
    ):
        return None, None
    litres = litres_for(amount, price)
    if litres > MAX_LITRES:
        raise HTTPException(status_code=400, detail=TOO_MANY_LITRES)
    return price, litres
