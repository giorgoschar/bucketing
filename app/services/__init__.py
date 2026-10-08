"""Service layer package; re-exports the public API so `from app.services import X` keeps working."""

from app.services.buckets import (  # noqa: F401
    get_bucket_balance,
    get_bucket_month_summary,
    get_bucket_spend_this_month,
    get_savings_summary,
    get_trip_summary,
)
from app.services.cash import (  # noqa: F401
    CashSpend,
    add_movement,
    cash_scope,
    cash_spending,
    delete_movement,
    delete_own_movement,
    list_movements,
    monthly_breakdown,
    not_yet_logged,
    parse_month,
    record_movement,
    record_stash_count,
    stash_balance,
    wallet_summaries,
    wallet_summary,
    withdraw_and_spend,
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
    duplicate_check,
    find_duplicate_candidates,
    find_household_duplicates,
)
from app.services.ingest import (  # noqa: F401
    coerce_amount,
    ingest_apple_pay,
    ingest_client_id,
    normalise_amount,
    notify_ingest_created,
    recent_ingest_attempts,
    record_ingest_attempt,
    token_from_raw,
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
    in_out,
    resolve_insight_period,
)
from app.services.money import (  # noqa: F401
    base_amount_expr,
    paid_for,
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
    revoke_user_tokens,
    token_dict,
)
from app.services.settlement import (  # noqa: F401
    SettlementChanged,
    compute_bucket_net,
    get_bucket_settlement,
    get_bucket_settlement_history,
    get_household_settlement,
    get_household_settlement_history,
    get_member_balances,
    get_settlement_exclusions,
    record_household_settlement,
    settlement_fingerprint,
    simplify_debts,
)
from app.services.stock import (  # noqa: F401
    StockError,
    add_product,
    adjust_stock,
    archive_product,
    current_prices,
    get_stock_item,
    list_stock,
    predicted_runout_days,
    price_advice,
    record_snapshots,
    retailer_label,
    rotation_suggestions,
    shopping_list,
    update_stock_settings,
)
from app.services.transactions import (  # noqa: F401
    ALLOWED_RECEIPT_EXTENSIONS,
    INCOME_LIST_URL,
    MAX_RECEIPT_SIZE,
    TRASH_DIRNAME,
    UPLOADS_DIR,
    DeletedTransactionReplay,
    DuplicateTransaction,
    after_save_url,
    create_transaction,
    delete_transaction,
    last_payment_method,
    update_transaction,
)
