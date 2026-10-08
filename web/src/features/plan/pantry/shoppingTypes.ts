/**
 * Plan › Pantry shopping-list wire types, hand-written from the pantry spec §3.2/§3.3 while the server
 * (stream B) is built in parallel. The integration step runs gen:api and turns these into aliases of the
 * generated schema.
 *
 * Money and quantities are JSON numbers on the wire: the server's Decimals go through FastAPI's encoder,
 * like the other stock routes (whose generated responses are still `unknown`).
 */

export type Advice = 'buy_now' | 'wait' | 'neutral' | 'unknown'

/** One computed row of GET /stock/shopping (`id` is the stock item's id). */
export interface ShoppingItem {
  id: string
  name: string
  unit: string | null
  need_qty: number
  /** Not in spec §3.2: the row's current stock, for "Low · 1 left". Shown only when the server sends it. */
  quantity?: number | null
  reason: 'low' | 'runout'
  runout_days_estimate: number | null
  retailer: string | null
  retailer_name: string | null
  price: number | null
  line_total: number | null
  advice: Advice
  advice_reason: string | null
  trend_pct_30d: number | null
  ticked: boolean
  tick_id: string | null
}

/** A store basket; `retailer` null is the unpriced group (the server sorts it last). */
export interface ShoppingGroup {
  retailer: string | null
  retailer_name: string | null
  total: number
  item_ids: string[]
}

/** The cheapest single store for the whole list: `covers` items, `missing` of the priced ones not stocked there. */
export interface BestSingleStore {
  retailer: string
  retailer_name: string
  total: number
  covers: number
  missing: number
}

/** An active one-off line. */
export interface ShoppingLine {
  id: string
  name: string
  quantity: number | null
  checked: boolean
}

export interface ShoppingOut {
  items: ShoppingItem[]
  groups: ShoppingGroup[]
  best_single_store: BestSingleStore | null
  total: number
  /** How many computed rows have no price. */
  unpriced: number
  lines: ShoppingLine[]
  /** Active ticks plus checked one-off lines. */
  ticked_count: number
}

/** POST /stock/shopping/ticks */
export interface TickIn { stock_item_id: string; quantity?: number }
export interface TickOut { id: string; stock_item_id: string; quantity: number | null }

/** POST /stock/shopping/lines */
export interface LineIn { name: string; quantity?: number | null }
/** PATCH /stock/shopping/lines/{id} */
export interface LinePatch { checked: boolean }

/** POST /stock/shopping/apply-ticked */
export interface AppliedOut { name: string; before: number; after: number }
export interface ApplyTickedOut { applied: AppliedOut[]; cleared_lines: number }

/** GET /stock/summary (spec §3.3) */
export interface StockSummary { low_count: number; ticked_count: number }

/** Replies of the routes above that the generated schema doesn't have yet (test/fakeApi.ts uses this). */
export interface ShoppingReplies {
  'GET /api/v1/stock/shopping': ShoppingOut
  'GET /api/v1/stock/summary': StockSummary
  'POST /api/v1/stock/shopping/ticks': TickOut
  'DELETE /api/v1/stock/shopping/ticks/{tick_id}': null
  'POST /api/v1/stock/shopping/lines': ShoppingLine
  'PATCH /api/v1/stock/shopping/lines/{line_id}': ShoppingLine
  'DELETE /api/v1/stock/shopping/lines/{line_id}': null
  'POST /api/v1/stock/shopping/apply-ticked': ApplyTickedOut
}
