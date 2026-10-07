/**
 * Plan › Pantry wire types, hand-written from the pantry spec §3.2 while the server (stream B) is built in
 * parallel. The integration step turns these into aliases of the generated schema (plan, Integration 2).
 *
 * Numbers: every quantity, price and unit price is a JSON number on the wire, as GET /stock sends them today
 * (Decimal through FastAPI's encoder). The new list fields are optional to older servers, so they may be
 * missing; read them through the helpers below.
 */

/** `price_advice`'s verdict; `buy_now` turns the price chip green. */
export type PriceAdvice = 'buy_now' | 'wait' | 'neutral' | 'unknown'

/** The cheapest latest snapshot of an item (GET /stock `cheapest`). */
export interface CheapestPrice {
  retailer: string
  retailer_name: string
  price: number | null
  unit_price: number | null
  is_discount: boolean
  /** YYYY-MM-DD */
  date: string
}

/** One GET /stock row, and what the stock writes return. */
export interface StockItem {
  id: string
  product_id: string
  name: string
  brand: string | null
  barcode: string | null
  posokanei_id: string | null
  quantity: number
  min_quantity: number
  track_price: boolean
  /** quantity <= min_quantity */
  low: boolean
  cheapest: CheapestPrice | null
  // Added by the pantry spec §3.2.
  unit?: string | null
  unit_quantity?: number | null
  image_url?: string | null
  /** restock_quantity: max(1, ceil(2*min − qty)) */
  need_qty?: number | null
  runout_days?: number | null
  advice?: PriceAdvice | null
  ticked?: boolean
  tick_id?: string | null
}

/** One store's latest price on the detail page. */
export interface PriceToday {
  retailer: string
  retailer_name: string
  price: number | null
  unit_price: number | null
  is_discount: boolean
}

/** One day's lowest price across retailers. */
export interface HistoryPoint {
  /** YYYY-MM-DD */
  date: string
  min_price: number
}

/** `price_advice`'s dict. */
export interface AdviceDetail {
  advice?: PriceAdvice
  current_min: number | null
  median_30d: number | null
  min_90d: number | null
  trend_pct_30d: number | null
  reason: string | null
  as_of: string | null
}

/** GET /stock/{id} and POST /stock/{id}/refresh. */
export interface StockDetail extends StockItem {
  /** Cheapest unit price first. */
  prices_today: PriceToday[]
  /** One point per day over the last 183 days. */
  history: HistoryPoint[]
  advice_detail: AdviceDetail | null
  prices_as_of: string | null
}

/** POST /stock. */
export interface StockAddBody {
  name: string
  brand?: string | null
  barcode?: string | null
  posokanei_id?: string | null
  unit?: string | null
  unit_quantity?: number | null
  image_url?: string | null
  quantity?: number
  min_quantity?: number
}

/** PATCH /stock/{id}. */
export interface StockSettingsBody {
  min_quantity?: number
  track_price?: boolean
}

/** POST /stock/{id}/adjust: a relative delta; `client_id` makes a replayed queued adjust apply once. */
export interface StockAdjustBody {
  delta: number
  client_id: string
}

// ---- PosoKanei lookups (GET /products/search, GET /products/barcode/{code}), unchanged but for in_pantry.

export interface RetailerPrice {
  retailer: string
  display_name: string
  price: number | null
  unit_price: number | null
  is_discount: boolean
  discount_pct: number | null
  last_updated: string | null
}

export interface ProductSummary {
  id: string
  name: string
  brand: string | null
  barcode: string | null
  unit: string | null
  unit_quantity: number | null
  image_url: string | null
  retailer_prices: RetailerPrice[]
  price_stats: { min: number | null; max: number | null; avg: number | null }
}

export interface BarcodeProduct extends ProductSummary {
  /** The household's item with this barcode, if any. */
  in_pantry?: { stock_item_id: string; quantity: number } | null
}

/**
 * The part of GET /stock/shopping the list's "Shopping list (N)" button reads: N is its items (low or
 * running out). Stream Wb owns the full shopping types; this is named so it never clashes with them.
 */
export interface PantryShoppingCount {
  items: { id: string }[]
}

/** A quantity as people write it: 2, 1.5, 0.25 (never 2.00). */
export function formatQty(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '0'
  return String(Math.round(n * 100) / 100)
}

/** "500 g", "1 L", or '' when the size is unknown. */
export function sizeLabel(p: { unit_quantity?: number | null; unit?: string | null }): string {
  if (p.unit_quantity == null || !p.unit) return ''
  return `${formatQty(p.unit_quantity)} ${p.unit}`
}

/** The cheapest priced store of a lookup result. */
export function bestPrice(p: ProductSummary): RetailerPrice | null {
  const priced = p.retailer_prices.filter((r) => r.price != null)
  return priced.length ? priced.reduce((a, b) => ((b.price as number) < (a.price as number) ? b : a)) : null
}

/** A stable tint per product for its initial tile (the kit's --c1..--c5 series). */
export function tintOf(name: string): string {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return `var(--c${(h % 5) + 1})`
}
