import type { StockDetail, StockSettingsBody } from './types'

/**
 * Polish round contracts C2–C4, hand-typed while the server builds them (stream S). Integration replaces
 * these with aliases of the generated schema after `gen:api`.
 */

/** C2: PATCH /stock/{id} also edits the product. `name` is 1–200 characters; a taken barcode is a 409. */
export type StockEditBody = StockSettingsBody & {
  name?: string
  brand?: string | null
  unit?: string | null
  unit_quantity?: number | null
  barcode?: string | null
}

/** C3: GET /stock/retailers, for the Log a price picker. */
export interface Retailer { code: string; name: string }

/** C3: POST /stock/{id}/prices. `retailer` is a chain code or "other"; `date` defaults to today on the server. */
export interface PriceIn { price: number; retailer: string; date?: string }

/** The replies of the routes above (and C4's DELETE /stock/shopping/ticks?stock_item_id=…, a 204). */
export interface PantryContractReplies {
  'POST /api/v1/stock/{item_id}/prices': StockDetail
  'GET /api/v1/stock/retailers': Retailer[]
  'DELETE /api/v1/stock/shopping/ticks': null
}
