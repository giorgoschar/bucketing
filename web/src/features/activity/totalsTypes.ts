/**
 * GET /api/v1/transactions/totals (polish plan contract C1), hand-written while the server (stream S) is built
 * in parallel. The integration step runs gen:api and turns these into aliases of the generated schema.
 *
 * Money is a JSON number, as TransactionOut.amount is typed in the generated schema. Totals are in the
 * household currency over every match of the feed filter (not only the loaded pages); soft-deleted rows are out.
 */
export interface TransactionTotals {
  count: number
  out: number
  in: number
}

/** The query params are the feed's filters (GET /transactions minus page and page_size). */
export interface TotalsPaths {
  '/api/v1/transactions/totals': {
    parameters: { query?: Record<string, string | boolean>; header?: never; path?: never; cookie?: never }
    get: {
      parameters: { query?: Record<string, string | boolean>; header?: never; path?: never; cookie?: never }
      requestBody?: never
      responses: { 200: { headers: { [name: string]: unknown }; content: { 'application/json': TransactionTotals } } }
    }
    put?: never; post?: never; delete?: never; options?: never; head?: never; patch?: never; trace?: never
  }
}

/** Replies of the routes above that the generated schema doesn't have yet (test/fakeApi.ts uses this). */
export interface ActivityReplies {
  'GET /api/v1/transactions/totals': TransactionTotals
}
