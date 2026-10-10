import { QueryClient } from '@tanstack/react-query'
import { expect, it } from 'vitest'
import { affects, keys } from '../../../data/keys'

/** Spec §5.7: after Pay, Undo, Skip, Set amount, an item edit or delete and an accepted match, both bill reads go stale. */
it.each(['entry', 'item', 'sync', 'cash'] as const)('affects.%s invalidates the Bills list and every bill history', (name) => {
  const qc = new QueryClient()
  qc.setQueryData(keys.insightsBills(), [])
  qc.setQueryData(keys.itemHistory('i1'), {})
  qc.setQueryData(keys.plan.pace(), {})
  for (const queryKey of affects[name]) void qc.invalidateQueries({ queryKey })
  expect(qc.getQueryState(keys.insightsBills())?.isInvalidated).toBe(true)
  expect(qc.getQueryState(keys.itemHistory('i1'))?.isInvalidated).toBe(true)
})
