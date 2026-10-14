import { afterEach, expect, it, vi } from 'vitest'
import { queryClient } from '../queryClient'
import { afterHouseholdChange } from './householdChange'

afterEach(() => vi.unstubAllGlobals())

it('empties the query cache and reloads the app', () => {
  queryClient.setQueryData(['plan', 'budgets'], [1])
  const assign = vi.fn()
  vi.stubGlobal('location', { assign })
  afterHouseholdChange()
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  expect(assign).toHaveBeenCalledWith('/app/')
})
