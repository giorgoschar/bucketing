// The Phase B API shapes: aliases of the generated schema (`npm run gen:api`), so a server change shows up in typecheck.
import type { components } from '../../../api/schema'

type S = components['schemas']

export type StatementPrevious = S['StatementPreviousOut']
export type StatementTotals = S['StatementTotalsOut']
export type PlannedSide = S['PlannedSideOut']
export type OpenEntry = S['OpenEntryOut']
export type StatementPlanned = S['StatementPlannedOut']
export type BudgetOver = S['BudgetOverOut']
export type BillChanged = S['BillChangedOut']
export type CashLeft = S['CashLeftOut']
export type CategoryOver = S['CategoryOverOut']
export type BiggestExpense = S['BiggestOut']

/** GET /api/v1/insights/statements/{month} and POST .../review. `reviewed_at` is naive UTC and is not shown;
 *  `reviewed_on` is the household-local date (YYYY-MM-DD). `reviewed_by` is a user id (= me.id, members[].user_id). */
export type StatementOut = S['StatementOut']
export type StatementReview = S['StatementReviewOut']
export type StatementListMonth = S['StatementMonthOut']
/** GET /api/v1/insights/statements. */
export type StatementListOut = S['StatementListOut']
