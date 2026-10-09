import type { components } from '../../../api/schema'
import type { StockSettingsBody } from './types'

/** C2: PATCH /stock/{id} also edits the product. `name` is 1-200 characters; a taken barcode is a 409. */
export type StockEditBody = StockSettingsBody

/** C3: GET /stock/retailers, for the Log a price picker. */
export type Retailer = components['schemas']['RetailerOut']

/** C3: POST /stock/{id}/prices. `retailer` is a chain code or "other"; `date` defaults to today on the server. */
export type PriceIn = components['schemas']['PriceIn']
