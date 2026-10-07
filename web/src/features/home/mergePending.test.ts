import { expect, it } from 'vitest'
import type { PendingView } from '../composer/hooks/usePendingTransactions'
import type { PendingRow } from '../composer/hooks/pendingStore'
import { mergePending } from './mergePending'

const row = (key: string, over: Partial<PendingRow> = {}): PendingRow => ({
  key, id: null, client_id: key, type: 'expense', amount: '3.00', currency: 'EUR', bucket_id: null, category_id: null,
  merchant: 'Coffee Island', transaction_date: '2026-10-07', state: 'waiting', ...over,
})
const view = (over: Partial<PendingView> = {}): PendingView => ({
  rows: [], edits: new Map(), hiddenIds: new Set(), waitingCount: 0, justSaved: null, ...over,
})
const server = [{ id: 't1' }, { id: 't2' }, { id: 't3' }]

it('pending rows first, hidden rows dropped, edits attached, the new one highlighted, capped', () => {
  const items = mergePending(server, view({
    rows: [row('c-1')], hiddenIds: new Set(['t2']), edits: new Map([['t3', row('t3', { id: 't3', amount: '9.00' })]]), justSaved: 't1',
  }), 3)
  expect(items.map((i) => (i.kind === 'pending' ? i.row.key : i.txn.id))).toEqual(['c-1', 't1', 't3'])
  expect(items[1]).toMatchObject({ kind: 'server', highlight: true, edit: null })
  expect(items[2]).toMatchObject({ kind: 'server', edit: { amount: '9.00' } })
})
