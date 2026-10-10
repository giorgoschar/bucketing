import type { components } from '../../../api/schema'

/**
 * Plan › Pantry wire types: aliases of the generated schema (pantry spec §3.2).
 *
 * Numbers: every quantity, price and unit price is a JSON number on the wire (the server's `Num`: a whole
 * Decimal is a JSON int, otherwise a float).
 */
type S = components['schemas']

/** `price_advice`'s verdict; `buy_now` turns the price chip green. */
export type PriceAdvice = S['StockItemOut']['advice']

/** The cheapest latest snapshot of an item (GET /stock `cheapest`). */
export type CheapestPrice = S['CheapestOut']

/** One GET /stock row, and what the stock writes (POST /stock, adjust, PATCH) return. */
export type StockItem = S['StockItemOut']

/** One store's latest price on the detail page. */
export type PriceToday = S['PriceTodayOut']

/** One day's lowest price across retailers. */
export type HistoryPoint = S['app__api__stock__HistoryPointOut']

/** `price_advice`'s dict. */
export type AdviceDetail = S['AdviceDetailOut']

/** GET /stock/{id} and POST /stock/{id}/refresh. */
export type StockDetail = S['StockDetailOut']

/** POST /stock. */
export type StockAddBody = S['StockAdd']

/** PATCH /stock/{id}. */
export type StockSettingsBody = S['StockSettingsIn']

/** POST /stock/{id}/adjust: a relative delta; `client_id` makes a replayed queued adjust apply once. */
export type StockAdjustBody = S['StockAdjust']

// ---- PosoKanei lookups (GET /products/search, GET /products/barcode/{code}).

export type RetailerPrice = S['RetailerPriceOut']

/** A search result. */
export type ProductSummary = S['ProductOut']

/** A barcode lookup; `in_pantry` is the household's item with this barcode (or PosoKanei id), if any. */
export type BarcodeProduct = S['ProductLookupOut']

/** The barcode lookup's 404 / 503 body: `detail` plus the pantry match, which a miss can still have. */
export type BarcodeLookupError = S['ProductLookupErrorOut']

/** A quantity as people write it: 2, 1.5, 0.25 (never 2.00). */
export function formatQty(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '0'
  return String(Math.round(n * 100) / 100)
}

/** "1,5" or "1.5" → 1.5; blank → the fallback; anything else → NaN. */
export function num(text: string, blank: number | null): number | null {
  const s = text.trim().replace(',', '.')
  if (s === '') return blank
  return /^\d+(\.\d+)?$/.test(s) ? Number(s) : NaN
}

/** A typed price ("1,29", "1.29", "2") as a number of euros: above 0, at most 2 decimals; null otherwise. */
export function typedPrice(text: string): number | null {
  const s = text.trim().replace(/[\s€]/g, '').replace(',', '.')
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null
  const n = Number(s)
  return n > 0 ? n : null
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
