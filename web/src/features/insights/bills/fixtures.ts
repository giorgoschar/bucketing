import type { Routes } from '../../../test/fakeApi'
import type { BillChange, BillRow, HistoryPoint, ItemHistoryOut } from './types'

export function change(over: Partial<BillChange> = {}): BillChange {
  return {
    entry_id: 'e9', amount: 84, usual: 61, basis: 'recent', delta: 23, pct: 37.7, direction: 'up', reason: null, reason_pct: null,
    ...over,
  }
}

export function billRow(over: Partial<BillRow> = {}): BillRow {
  return {
    item_id: 'i1', name: 'Electricity', category_id: null, usage_unit: 'kWh', is_active: true,
    last: { entry_id: 'e9', due_date: '2026-09-14', amount: 84 }, recent: [61, 58.5, 70.2, 84],
    total_12m: 790.4, average_12m: 65.87, change: null, ...over,
  }
}

export function point(over: Partial<HistoryPoint> = {}): HistoryPoint {
  return { entry_id: 'p1', due_date: '2026-09-14', amount: 84, usage: null, unit_price: null, transaction_id: null, ...over }
}

export function history(over: Partial<ItemHistoryOut> = {}): ItemHistoryOut {
  return {
    item: { id: 'i1', name: 'Electricity', direction: 'out', currency: 'EUR', usage_unit: 'kWh', category_id: null, is_active: true },
    points: [], change: null, ...over,
  }
}

/** Routes for the Bills list; `extra` adds more. */
export function billsRoutes(rows: BillRow[] = [], extra: Routes = {}): Routes {
  return { 'GET /api/v1/insights/bills': () => rows, ...extra }
}
