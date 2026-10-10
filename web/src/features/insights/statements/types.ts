// The Phase B API shapes, hand-typed from the spec (§3.2 to §3.4) until `npm run gen:api` has the routes.
// At integration, replace each with an alias of components['schemas'][...] and let typecheck show the drift.

export interface StatementPrevious { month: string; in: number; out: number; net: number }

export interface StatementTotals { in: number; out: number; net: number; previous: StatementPrevious | null }

export interface PlannedSide { planned: number; actual: number }

export interface OpenEntry {
  entry_id: string
  item_id: string
  name: string
  direction: 'in' | 'out'
  due_date: string
  amount: number | null
  estimated: boolean
  status: 'expected'
}

export interface StatementPlanned { in: PlannedSide; out: PlannedSide; open: OpenEntry[] }

export interface BudgetOver { bucket_id: string; name: string; budget: number; spent: number; over: number }

/** `basis`, `direction` and `reason` are plain strings on the wire, like Phase A's BillChangeOut. */
export interface BillChanged {
  item_id: string
  name: string
  entry_id: string
  due_date: string
  amount: number
  usual: number
  basis: 'recent' | 'last_year'
  direction: 'up' | 'down'
  pct: number
  reason: 'usage' | 'price' | null
  reason_pct: number | null
}

export interface CashLeft { member_id: string; name: string; not_yet_logged: number }

export interface CategoryOver { category_id: string | null; name: string; icon: string; amount: number; usual: number | null }

export interface BiggestExpense { transaction_id: string; date: string; label: string; category: string | null; amount: number }

/** GET /api/v1/insights/statements/{month} and POST .../review (§3.2, §3.4). `reviewed_at` is naive UTC and is not
 *  shown; `reviewed_on` is the household-local date (YYYY-MM-DD). `reviewed_by` is a user id (= me.id, members[].user_id). */
export interface StatementOut {
  month: string
  label: string
  reviewed_at: string | null
  reviewed_on: string | null
  reviewed_by: string | null
  reviewed_by_name: string | null
  closed: boolean
  days_left: number | null
  totals: StatementTotals
  planned: StatementPlanned
  budgets_over: BudgetOver[]
  bills_changed: BillChanged[]
  cash: CashLeft[]
  categories_over: CategoryOver[]
  biggest: BiggestExpense[]
}

export interface StatementReview { month: string; label: string; days_left: number }

export interface StatementListMonth {
  month: string
  label: string
  in: number
  out: number
  net: number
  reviewed_at: string | null
  reviewed_on: string | null
  reviewed_by: string | null
  reviewed_by_name: string | null
  closed: boolean
}

/** GET /api/v1/insights/statements (§3.3). */
export interface StatementListOut { review: StatementReview | null; months: StatementListMonth[] }
