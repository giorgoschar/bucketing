import { QueryClient } from '@tanstack/react-query'
import { expect, it } from 'vitest'
import { affects, keys } from '../../../data/keys'
import { afterTxnWrite } from '../../composer/bridge'

const seeded = () => {
  const qc = new QueryClient()
  qc.setQueryData(keys.statements(), {})
  qc.setQueryData(keys.statement('2026-09'), {})
  qc.setQueryData(keys.plan.pace(), {})
  return qc
}
const stale = (qc: QueryClient) => [keys.statements(), keys.statement('2026-09')].map((k) => qc.getQueryState(k)?.isInvalidated)

/** Spec §4.8: a transaction write, an entry write, a cash write, an item edit or delete and Done make both reads stale. */
it.each(['entry', 'item', 'sync', 'cash'] as const)('affects.%s invalidates the list and every statement', (name) => {
  const qc = seeded()
  for (const queryKey of affects[name]) void qc.invalidateQueries({ queryKey })
  expect(stale(qc)).toEqual([true, true])
})

it('a transaction write (create, edit, delete) invalidates the list and every statement', () => {
  const qc = seeded()
  for (const queryKey of afterTxnWrite) void qc.invalidateQueries({ queryKey })
  expect(stale(qc)).toEqual([true, true])
})

it('the statements prefix covers both reads (what Done invalidates)', () => {
  const qc = seeded()
  void qc.invalidateQueries({ queryKey: keys.statementsAll() })
  expect(stale(qc)).toEqual([true, true])
  expect(qc.getQueryState(keys.plan.pace())?.isInvalidated).toBe(false)
})
