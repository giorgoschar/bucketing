import type { Routes } from '../../../test/fakeApi'
import type { StatementListMonth, StatementListOut, StatementOut } from './types'

export function listMonth(over: Partial<StatementListMonth> = {}): StatementListMonth {
  return { month: '2026-09', label: 'September 2026', in: 3000, out: 2240, net: 760, reviewed_at: null, closed: false, ...over }
}

export function statementList(over: Partial<StatementListOut> = {}): StatementListOut {
  return { review: null, months: [], ...over }
}

/** A statement with every section empty; tests add what they look at. */
export function statement(over: Partial<StatementOut> = {}): StatementOut {
  return {
    month: '2026-09', label: 'September 2026', reviewed_at: null, reviewed_by: null, closed: false, days_left: 3,
    totals: { in: 3000, out: 2240, net: 760, previous: { month: '2026-08', in: 3000, out: 2000, net: 1000 } },
    planned: { in: { planned: 3000, actual: 3000 }, out: { planned: 910, actual: 934 }, open: [] },
    budgets_over: [], bills_changed: [], cash: [], categories_over: [], biggest: [],
    ...over,
  }
}

/** The Phase B routes are not in the generated schema, so the typed Routes map needs one cast. */
const asRoutes = (r: Record<string, unknown>) => r as unknown as Routes

export const listRoutes = (list: StatementListOut, extra: Routes = {}): Routes =>
  ({ ...asRoutes({ 'GET /api/v1/insights/statements': () => list }), ...extra })

export const statementRoutes = (s: StatementOut, extra: Routes = {}): Routes =>
  ({ ...asRoutes({ [`GET /api/v1/insights/statements/${s.month}`]: () => s }), ...extra })

export { asRoutes }
