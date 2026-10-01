"""Service layer package; re-exports the public API so `from app.services import X` keeps working."""
from app.services.buckets import (  # noqa: F401
    get_bucket_balance,
    get_bucket_month_summary,
    get_bucket_spend_this_month,
    get_savings_summary,
    get_trip_summary,
)
from app.services.cash import (  # noqa: F401
    add_movement,
    can_manage_for,
    cash_comparison,
    delete_movement,
    list_movements,
    member_balances,
    parse_month,
)
from app.services.context import (  # noqa: F401
    base_ctx,
    full_ctx,
)
from app.services.dashboard import (  # noqa: F401
    get_all_time_summary,
    get_month_summary,
    get_overdue_bills,
    get_upcoming_bills,
)
from app.services.duplicates import (  # noqa: F401
    DUPLICATE_AMOUNT_TOLERANCE,
    DUPLICATE_WINDOW_DAYS,
    find_duplicate_candidates,
    find_household_duplicates,
)
from app.services.insights import (  # noqa: F401
    INSIGHT_PRESETS,
    InsightFilters,
    build_insights,
    get_bills_due_month_total,
    get_forecast,
    get_income_total,
    get_insights_bills_due,
    get_insights_bucket_breakdown,
    get_insights_budget_status,
    get_insights_category_breakdown,
    get_insights_category_trend,
    get_insights_income,
    get_insights_kpis,
    get_insights_summary,
    get_monthly_trend,
    resolve_insight_period,
)
from app.services.money import (  # noqa: F401
    base_amount_expr,
    shares_for,
    split_to_base,
    to_base,
)
from app.services.person import (  # noqa: F401
    get_person_summary,
)
from app.services.personal_tokens import (  # noqa: F401
    active_household_bucket,
    hash_personal_token,
    issue_personal_token,
    list_personal_tokens,
    revoke_personal_token,
    token_dict,
)
from app.services.settlement import (  # noqa: F401
    compute_bucket_net,
    get_bucket_settlement,
    get_bucket_settlement_history,
    get_household_settlement,
    get_household_settlement_history,
    get_member_balances,
    get_settlement_exclusions,
    record_household_settlement,
    simplify_debts,
)
from app.services.transactions import (  # noqa: F401
    ALLOWED_RECEIPT_EXTENSIONS,
    MAX_RECEIPT_SIZE,
    TRASH_DIRNAME,
    UPLOADS_DIR,
    DeletedTransactionReplay,
    DuplicateTransaction,
    create_transaction,
    delete_transaction,
)
