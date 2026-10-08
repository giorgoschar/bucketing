import type {
  Bucket, BudgetRowOut, Category, CategoryUsualOut, EntryOut, Household, MatchOut, Member, MonthPictureOut,
  PaceOut, RecurringItemOut, TransactionRow, UpcomingDayOut, YearMonthOut, YearOut,
} from '../data/types'
import type { components } from '../api/schema'
import { reply, type Routes } from './fakeApi'
import type { CashMovementOut, CashWalletMemberOut, CashWalletsOut, WalletOut } from '../features/plan/cash/types'
import type { BarcodeProduct, ProductSummary, StockDetail, StockItem } from '../features/plan/pantry/types'
import type { ShoppingItem, ShoppingOut } from '../features/plan/pantry/shoppingTypes'

/** Cosmote, out, €38.90, due Fri 9 Oct 2026, expected. */
export function entry(over: Partial<EntryOut> = {}): EntryOut {
  return {
    id: 'e1', item_id: 'i1', name: 'Cosmote', direction: 'out', due_date: '2026-10-09', status: 'expected',
    amount: 38.9, estimated: false, currency: 'EUR', bucket_id: null, category_id: null, transaction_id: null,
    overdue: false, infrequent: false, payment_method: 'card', ...over,
  }
}

export function day(date: string, entries: EntryOut[], net_this_month: number): UpcomingDayOut {
  return { date, entries, net_this_month }
}

export function item(over: Partial<RecurringItemOut> = {}): RecurringItemOut {
  return {
    id: 'i1', name: 'Cosmote', direction: 'out', amount: 38.9, currency: 'EUR', category_id: null, bucket_id: null,
    rule_kind: 'monthly_day', interval_months: 1, rule_day: 9, rule_month: null, rule_adjust: 'none', rule_days: null,
    rule_weekday: null, rule_interval_weeks: null, start_date: '2026-01-09', end_date: null, total_occurrences: null,
    contract_end_date: null, paid_by_default: 'u1', payer_mode: 'single', is_auto_pay: false, is_active: true,
    notes: null, splits: [], next_entry: entry(), has_history: false, payment_method: 'card', ...over,
  }
}

/** October 2026: in 3,150 so far, net projected +2,311.10. */
export function monthPicture(over: Partial<MonthPictureOut> = {}): MonthPictureOut {
  return {
    month: '2026-10',
    income: { so_far: 3150, still_to_come: 1500, projected: 4650 },
    fixed: { so_far: 600, still_to_come: 238.9, projected: 838.9 },
    buckets: {
      so_far: 685, still_to_come: 815, projected: 1500,
      rows: [
        { bucket_id: 'b1', name: 'Day to day', budget: 1200, so_far: 685, still_to_come: 515, projected: 1200 },
        { bucket_id: 'b2', name: 'Kids', budget: null, so_far: 0, still_to_come: 300, projected: 300 },
      ],
    },
    net_projected: 2311.1, events_spent: 410, cash: 45, estimated: false, ...over,
  }
}

export function yearMonth(month: string, income: number, out: number, estimated = false): YearMonthOut {
  return { month, income, out, estimated }
}
export function yearOut(months: YearMonthOut[], over: Partial<YearOut> = {}): YearOut {
  return { months, infrequent_monthly_average: 42.5, estimated: false, ...over }
}

export function budgetRow(over: Partial<BudgetRowOut> = {}): BudgetRowOut {
  return {
    bucket_id: 'b1', name: 'Day to day', kind: 'monthly', budget: 1200, spent: 904, pct: 75.3,
    period_start: '2026-10-01', period_end: '2026-10-31', days_left: null, archive_suggested: false, ...over,
  }
}
export function pace(over: Partial<PaceOut> = {}): PaceOut {
  return { bucket_id: 'b1', name: 'Day to day', budget: 1200, spent: 904, pct: 75.3, pace: 1310, over_pace: true, ...over }
}

export function match(over: Partial<MatchOut> = {}): MatchOut {
  return {
    id: 'm1', label: 'Cosmote', transaction_id: 't1', transaction_date: '2026-10-03', transaction_amount: 38.9,
    merchant: 'Cosmote', notes: null, entry: entry({ due_date: '2026-10-05' }), ...over,
  }
}

export function categoryUsual(over: Partial<CategoryUsualOut> = {}): CategoryUsualOut {
  return { category_id: 'c1', name: 'Groceries', icon: '🛒', color: '#f59e0b', this_month: 412, usual: 300, flagged: true, ...over }
}

export function member(over: Partial<Member> = {}): Member {
  return { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'giorgos', avatar_color: null, ...over }
}
export function household(
  members: Member[] = [member(), member({ user_id: 'u2', role: 'member', display_name: 'Maria', username: 'maria' })],
): Household {
  return { id: 'h1', name: 'Home', default_currency: 'EUR', members }
}

export function txn(over: Partial<TransactionRow> = {}): TransactionRow {
  return {
    id: 't1', type: 'expense', amount: 64.2, currency: 'EUR', transaction_date: '2026-10-06', merchant: 'Sklavenitis',
    notes: null, bucket_id: 'b1', category_id: null, paid_by: 'u1', payment_method: 'card', recurring_bill_id: null, ...over,
  }
}
// GET /transactions is the typed Activity feed since 2c-B2: each row is the full
// TransactionOut and the page carries day_totals. The 2a reader ignores the extras.
export function page(items: TransactionRow[]): components['schemas']['TransactionPage'] {
  return {
    total: items.length, page: 1, page_size: 10, day_totals: {},
    items: items.map((r) => ({
      household_id: 'h1', exchange_rate: 1, payer_mode: 'single', receipt_path: null, fuel_price_per_litre: null,
      fuel_litres: null, exclude_from_forecast: false, exclude_from_settlement: false, created_at: null,
      splits: [], has_take: false, missing_payer: false, ...r, payment_method: r.payment_method ?? 'card',
    })),
  }
}

export function bucket(over: Partial<Bucket> = {}): Bucket {
  return { id: 'b1', name: 'Day to day', kind: 'monthly', status: 'active', budget: 1200, start_date: null, end_date: null, show_income: false, ...over }
}
export function category(over: Partial<Category> = {}): Category {
  return { id: 'c1', name: 'Groceries', icon: '🛒', color: '#f59e0b', system_key: null, is_default: false, locked: false, expense_count: 0, rule_count: 0, ...over }
}

/** Handlers for the shared reads in data/reads.ts (household, items, buckets, categories). */
export function readRoutes(): Routes {
  return {
    'GET /api/v1/settings/household': () => household(),
    'GET /api/v1/recurring': () => [item()],
    'GET /api/v1/buckets': () => [bucket()],
    'GET /api/v1/settings/categories': () => [category()],
  }
}

// ---- Plan › Cash (cash spec §3.2/§3.3).

/** Giorgos (u1, the viewer) took €120 and logged €75: €45 not yet logged. */
export function wallet(over: Partial<WalletOut> = {}): WalletOut {
  return {
    carried: 0, taken: 120, put_back: 0, still_have: null, spent: 120, logged: 75, outs: 0, not_yet_logged: 45, ...over,
  }
}
export function walletMember(over: Partial<CashWalletMemberOut> = {}): CashWalletMemberOut {
  return { member_id: 'u1', name: 'Giorgos', is_me: true, wallet: wallet(), ...over }
}
/** October 2026: stash €380; Giorgos €45 not logged, Maria all logged. */
export function cashWallets(over: Partial<CashWalletsOut> = {}): CashWalletsOut {
  return {
    month: '2026-10',
    stash: 380,
    members: [
      walletMember(),
      walletMember({
        member_id: 'u2', name: 'Maria', is_me: false,
        wallet: wallet({ taken: 60, put_back: null, spent: 60, logged: 60, not_yet_logged: 0 }),
      }),
    ],
    ...over,
  }
}
export function cashMovement(over: Partial<CashMovementOut> = {}): CashMovementOut {
  return {
    id: 'm1', user_id: 'u1', kind: 'take', stash_owner_id: null, amount: 40, currency: 'EUR', category_id: null,
    note: null, movement_date: '2026-10-04', transaction_id: null, created_at: '2026-10-04T10:00:00', deleted: false, ...over,
  }
}
export function cashRoutes(
  o: { wallets?: CashWalletsOut; movements?: CashMovementOut[] } = {},
): Routes {
  const wallets = o.wallets ?? cashWallets()
  return {
    'GET /api/v1/cash/wallets': () => wallets,
    'GET /api/v1/cash/movements': () => ({ items: o.movements ?? [], stash: wallets.stash }),
    'POST /api/v1/cash/movements': () => Response.json(cashMovement({ id: 'new' }), { status: 201 }),
    'DELETE /api/v1/cash/movements/{movement_id}': () => null,
  }
}

// ---- Plan › Pantry (pantry spec §3.2).

/** Barilla spaghetti 500 g: 3 left, keep at least 1, cheapest €1.19 at Sklavenitis. */
export function stockItem(over: Partial<StockItem> = {}): StockItem {
  return {
    id: 's1', product_id: 'p1', name: 'Barilla spaghetti', brand: 'Barilla', barcode: '8076802085738', posokanei_id: 'pk1',
    quantity: 3, min_quantity: 1, track_price: false, low: false,
    cheapest: {
      retailer: 'sklavenitis', retailer_name: 'Sklavenitis', price: 1.19, unit_price: 2.38, is_discount: false, date: '2026-10-08',
    },
    unit: 'g', unit_quantity: 500, image_url: null, need_qty: 1, runout_days: null, advice: 'neutral', ticked: false, tick_id: null,
    ...over,
  }
}

// ---- Plan › Pantry: the shopping list (pantry spec §3.2/§3.3), hand-typed until gen:api.

/** Olive oil ×1 at Lidl, €8.49: low, 1 left. */
export function shoppingItem(over: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: 's-oil', name: 'Olive oil', unit: null, need_qty: 1, quantity: 1, reason: 'low', runout_days_estimate: null,
    retailer: 'lidl', retailer_name: 'Lidl', price: 8.49, line_total: 8.49, advice: 'neutral', advice_reason: null,
    trend_pct_30d: null, ticked: false, tick_id: null, ...over,
  }
}

/**
 * Lidl: Olive oil ×1 €8.49 and Milk ×2 €2.18 (€10.67). Sklavenitis: Barilla ×2 €2.38, runs out in ~5 d.
 * No price: Salt. Total €13.05; Lidl alone would be €15.45 (saves €2.40). One unchecked one-off line.
 */
export function shoppingOut(over: Partial<ShoppingOut> = {}): ShoppingOut {
  const items = [
    shoppingItem(),
    shoppingItem({ id: 's-milk', name: 'Milk', need_qty: 2, quantity: 0, price: 1.09, line_total: 2.18 }),
    shoppingItem({
      id: 's-pasta', name: 'Barilla spaghetti', need_qty: 2, quantity: 3, reason: 'runout', runout_days_estimate: 5,
      retailer: 'sklavenitis', retailer_name: 'Sklavenitis', price: 1.19, line_total: 2.38, advice: 'buy_now',
    }),
    shoppingItem({ id: 's-salt', name: 'Salt', quantity: 0, retailer: null, retailer_name: null, price: null, line_total: null }),
  ]
  return {
    items,
    groups: [
      { retailer: 'lidl', retailer_name: 'Lidl', total: 10.67, item_ids: ['s-oil', 's-milk'] },
      { retailer: 'sklavenitis', retailer_name: 'Sklavenitis', total: 2.38, item_ids: ['s-pasta'] },
      { retailer: null, retailer_name: null, total: 0, item_ids: ['s-salt'] },
    ],
    best_single_store: { retailer: 'lidl', retailer_name: 'Lidl', total: 15.45, covers: 3, missing: 0 },
    total: 13.05,
    unpriced: 1,
    lines: [{ id: 'l1', name: 'Batteries', quantity: null, checked: false }],
    ticked_count: 0,
    ...over,
  }
}

/** Milk 1 L: none left, keep at least 1, need 2, no price. */
export function lowMilk(over: Partial<StockItem> = {}): StockItem {
  return stockItem({
    id: 's2', product_id: 'p2', name: 'Milk', brand: 'Delta', barcode: null, posokanei_id: null, quantity: 0, min_quantity: 1,
    low: true, cheapest: null, unit: 'L', unit_quantity: 1, need_qty: 2, advice: 'unknown', ...over,
  })
}

export function stockDetail(over: Partial<StockDetail> = {}): StockDetail {
  return {
    ...stockItem(),
    prices_today: [
      { retailer: 'sklavenitis', retailer_name: 'Sklavenitis', price: 1.19, unit_price: 2.38, is_discount: true },
      { retailer: 'lidl', retailer_name: 'Lidl', price: 1.29, unit_price: 2.58, is_discount: false },
      { retailer: 'ab', retailer_name: 'AB', price: 1.45, unit_price: 2.9, is_discount: false },
    ],
    history: [
      { date: '2026-05-01', min_price: 1.49 },
      { date: '2026-08-01', min_price: 1.09 },
      { date: '2026-10-08', min_price: 1.19 },
    ],
    advice_detail: {
      advice: 'neutral', current_min: 1.19, median_30d: 1.29, min_90d: 1.09, trend_pct_30d: -3.1, reason: 'Close to the usual price', is_discount: true, as_of: '2026-10-08',
    },
    prices_as_of: '2026-10-08',
    ...over,
  }
}

/** A PosoKanei search result: Dodoni feta 400 g, best €5.29 at Lidl. */
export function productSummary(over: Partial<ProductSummary> = {}): ProductSummary {
  return {
    id: 'pk-feta', name: 'Dodoni Feta PDO', brand: 'Dodoni', barcode: '5201004021108', unit: 'g', unit_quantity: 400,
    image_url: null, history: [],
    retailer_prices: [
      { retailer: 'sklavenitis', display_name: 'Sklavenitis', price: 5.89, unit_price: 14.73, is_discount: false, discount_pct: null, last_updated: '2026-10-08' },
      { retailer: 'lidl', display_name: 'Lidl', price: 5.29, unit_price: 13.23, is_discount: false, discount_pct: null, last_updated: '2026-10-08' },
    ],
    price_stats: { min: 5.29, max: 5.89, avg: 5.59 },
    ...over,
  }
}

export function barcodeProduct(over: Partial<BarcodeProduct> = {}): BarcodeProduct {
  return { ...productSummary(), in_pantry: null, ...over }
}

/** Handlers for the Pantry list: the household, GET /stock and the shopping list count. */
export function pantryRoutes(o: { items?: StockItem[]; shopping?: ShoppingItem[] } = {}): Routes {
  // A small server: adjusts change what the next GET /stock returns.
  const items = (o.items ?? [stockItem(), lowMilk()]).map((i) => ({ ...i }))
  return {
    ...readRoutes(),
    'GET /api/v1/stock': () => items.map((i) => ({ ...i })),
    'GET /api/v1/stock/shopping': () => shoppingOut({ items: o.shopping ?? [shoppingItem({ id: 's2', name: 'Milk' })], groups: [], lines: [] }),
    'POST /api/v1/stock/{item_id}/adjust': (req) => {
      const it = items.find((i) => i.id === req.params.item_id)
      if (!it) return Response.json({ detail: 'Stock item not found' }, { status: 404 })
      it.quantity = Math.max(0, it.quantity + Number((req.body as { delta: number }).delta))
      it.low = it.quantity <= it.min_quantity
      return { ...it }
    },
  }
}

/** A small stateful server: ticks, lines and apply-ticked change what the next GET returns. */
export function shoppingRoutes(initial: ShoppingOut = shoppingOut()): Routes {
  let data: ShoppingOut = structuredClone(initial)
  let seq = 0
  const count = () => data.items.filter((i) => i.ticked).length + data.lines.filter((l) => l.checked).length
  const recount = () => { data = { ...data, ticked_count: count() } }
  return {
    'GET /api/v1/stock/shopping': () => structuredClone(data),
    'GET /api/v1/stock/summary': () => ({ low_count: 3, ticked_count: data.ticked_count }),
    // Like the server (pantry fix round 1, I2): the client's `id` names the new tick; an item already ticked
    // returns its existing tick (whatever its id); a replayed id returns the row as it is now.
    'POST /api/v1/stock/shopping/ticks': (r) => {
      const b = r.body as { id?: string; stock_item_id: string }
      const id = b.stock_item_id
      const found = data.items.find((i) => i.id === id)
      if (!found) return reply(404, { detail: 'Stock item not found' })
      const tickId = found.tick_id ?? b.id ?? `tick-${++seq}`
      data = { ...data, items: data.items.map((i) => (i.id === id ? { ...i, ticked: true, tick_id: tickId } : i)) }
      recount()
      return { id: tickId, stock_item_id: id, quantity: found.need_qty }
    },
    'DELETE /api/v1/stock/shopping/ticks/{tick_id}': (r) => {
      data = { ...data, items: data.items.map((i) => (i.tick_id === r.params.tick_id ? { ...i, ticked: false, tick_id: null } : i)) }
      recount()
      return null
    },
    // C4: the item's active tick, whoever made it; 204 when there is none.
    'DELETE /api/v1/stock/shopping/ticks': (r) => {
      const item = r.query.get('stock_item_id')
      data = { ...data, items: data.items.map((i) => (i.id === item ? { ...i, ticked: false, tick_id: null } : i)) }
      recount()
      return null
    },
    'POST /api/v1/stock/shopping/lines': (r) => {
      const b = r.body as { id?: string; name: string; quantity?: number }
      const again = b.id ? data.lines.find((l) => l.id === b.id) : undefined
      if (again) return Response.json(again, { status: 201 })
      const line = { id: b.id ?? `l-new-${++seq}`, name: b.name, quantity: b.quantity ?? null, checked: false }
      data = { ...data, lines: [...data.lines, line] }
      return line
    },
    'PATCH /api/v1/stock/shopping/lines/{line_id}': (r) => {
      const checked = (r.body as { checked: boolean }).checked
      data = { ...data, lines: data.lines.map((l) => (l.id === r.params.line_id ? { ...l, checked } : l)) }
      recount()
      return data.lines.find((l) => l.id === r.params.line_id) ?? reply(404, { detail: 'Not found' })
    },
    'DELETE /api/v1/stock/shopping/lines/{line_id}': (r) => {
      data = { ...data, lines: data.lines.filter((l) => l.id !== r.params.line_id) }
      recount()
      return null
    },
    'POST /api/v1/stock/shopping/apply-ticked': () => {
      const applied = data.items.filter((i) => i.ticked).map((i) => ({ stock_item_id: i.id, name: i.name, before: i.quantity ?? 0, after: (i.quantity ?? 0) + i.need_qty }))
      const cleared = data.lines.filter((l) => l.checked).length
      data = { ...data, items: data.items.map((i) => ({ ...i, ticked: false, tick_id: null })), lines: data.lines.filter((l) => !l.checked), ticked_count: 0 }
      return { applied, cleared_lines: cleared }
    },
  }
}
