import type { components } from '../../../api/schema'

/**
 * Plan › Pantry shopping-list wire types: aliases of the generated schema (pantry spec §3.2/§3.3).
 * Money and quantities are JSON numbers on the wire.
 */
type S = components['schemas']

/**
 * One computed row of GET /stock/shopping (`id` is the stock item's id). `reason` is `low`, `runout`, or
 * `ticked` (an item that is neither but has an active tick); `quantity` is the current stock.
 */
export type ShoppingItem = S['ShoppingRowOut']

/** A store basket; `retailer` null is the unpriced group (the server sorts it last). */
export type ShoppingGroup = S['ShoppingGroupOut']

/** The cheapest single store for the whole list: `covers` items, `missing` of the priced ones not stocked there. */
export type BestSingleStore = S['BestStoreOut']

/** An active one-off line. */
export type ShoppingLine = S['ShoppingLineOut']

/** `ticked_count` is active ticks plus checked one-off lines; `unpriced` how many rows have no price. */
export type ShoppingOut = S['ShoppingOut']

/** POST /stock/shopping/ticks: `id` is the client's uuid4, so a replayed create is idempotent. */
export type TickIn = S['TickIn']
export type TickOut = S['TickOut']

/** POST /stock/shopping/lines: `id` as for ticks. */
export type LineIn = S['LineIn']
/** PATCH /stock/shopping/lines/{id} */
export type LinePatch = S['LineCheckIn']

/** POST /stock/shopping/apply-ticked */
export type AppliedOut = S['AppliedOut']
export type ApplyTickedOut = S['ApplyTickedOut']

/** GET /stock/summary (spec §3.3) */
export type StockSummary = S['StockSummaryOut']
