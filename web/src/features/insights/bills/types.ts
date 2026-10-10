// The Phase A API shapes, as the generated schema has them (src/api/schema.d.ts).
import type { components } from '../../../api/schema'

type S = components['schemas']

/** §3.4: the change of the latest done entry against its baseline. `basis`, `direction` and `reason` are
 *  plain strings in the schema; the narrower unions below are what the server sends. */
export type BillChange = S['BillChangeOut']
export type HistoryPoint = S['app__api__planning_models__HistoryPointOut']
export type HistoryItem = S['HistoryItemOut']
export type ItemHistoryOut = S['ItemHistoryOut']
export type BillRow = S['BillRowOut']
