import type { components } from '../../api/schema'

/** GET /api/v1/transactions/totals: count, money out and money in over every match of the feed filter. */
export type TransactionTotals = components['schemas']['TotalsOut']
