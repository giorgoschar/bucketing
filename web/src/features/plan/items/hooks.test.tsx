import { act, renderHook, waitFor } from '@testing-library/react'
import type { QueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { keys } from '../../../data/keys'
import { isPending } from '../../../data/pending'
import type { RecurringItemOut } from '../../../data/types'
import { setIdentity } from '../../../offline/identity'
import { fakeApi, reply } from '../../../test/fakeApi'
import { item } from '../../../test/fixtures'
import { Providers, resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../../../test/render'
import { emptyItemForm, formToBody } from './form'
import { useDebouncedValue, useItemActions, useRulePreview } from './hooks'
import type { RuleChoice } from './rule'

const PREVIEW = 'POST /api/v1/recurring/preview' as const
const wrap = (client: QueryClient = testQueryClient()) =>
  ({ children }: { children: ReactNode }) => <Providers client={client}>{children}</Providers>
const salary = (day: number): RuleChoice => ({ kind: 'monthly_day', day, adjust: 'previous_business_day', everyMonths: 1 })

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('useDebouncedValue settles 300 ms after the last change', () => {
  vi.useFakeTimers()
  const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), { initialProps: { v: 1 } })
  rerender({ v: 2 })
  act(() => { vi.advanceTimersByTime(200) })
  rerender({ v: 3 })
  act(() => { vi.advanceTimersByTime(299) })
  expect(result.current).toBe(1)
  act(() => { vi.advanceTimersByTime(1) })
  expect(result.current).toBe(3)
})

it('previews the first rule at once, then only the last of a quick series of edits', async () => {
  const fake = fakeApi({ [PREVIEW]: () => ({ dates: ['2026-10-26', '2026-11-25', '2026-12-23'] }) })
  const { result, rerender } = renderHook(({ day }) => useRulePreview(salary(day), '2026-10-01', ''), {
    initialProps: { day: 26 }, wrapper: wrap(),
  })
  await waitFor(() => expect(result.current).toEqual({ state: 'ready', dates: ['2026-10-26', '2026-11-25', '2026-12-23'] }))
  expect(fake.callsTo(PREVIEW)[0].body).toEqual({
    rule_kind: 'monthly_day', interval_months: 1, rule_day: 26, rule_month: null, rule_adjust: 'previous_business_day',
    rule_days: null, rule_weekday: null, rule_interval_weeks: null, start_date: '2026-10-01', end_date: null, count: 3,
  })
  rerender({ day: 2 })
  rerender({ day: 25 })
  await waitFor(() => expect(fake.callsTo(PREVIEW)).toHaveLength(2))
  expect(fake.callsTo(PREVIEW)[1].body).toMatchObject({ rule_day: 25 })
  await new Promise((r) => setTimeout(r, 350))
  expect(fake.callsTo(PREVIEW)).toHaveLength(2) // day 2 was never sent
})

it('offline: "needs a connection" and no request', () => {
  const fake = fakeApi({})
  setOnline(false)
  const { result } = renderHook(() => useRulePreview(salary(26), '2026-10-01', ''), { wrapper: wrap() })
  expect(result.current).toEqual({ state: 'offline' })
  expect(fake.calls).toHaveLength(0)
})

it("a rule the server refuses shows the server's message", async () => {
  fakeApi({ [PREVIEW]: () => reply(400, { detail: 'The day must be 1 to 31.' }) })
  const { result } = renderHook(() => useRulePreview(salary(26), '2026-10-01', ''), { wrapper: wrap() })
  await waitFor(() => expect(result.current).toEqual({ state: 'error', message: 'The day must be 1 to 31.' }))
})

it('creating offline shows the item at once, marked pending', async () => {
  fakeApi({})
  setOnline(false)
  const client = testQueryClient()
  client.setQueryData(keys.recurring.list(), [item()])
  const { result } = renderHook(() => useItemActions(), { wrapper: wrap(client) })
  const body = formToBody({ ...emptyItemForm('2026-10-07', 'u1'), name: 'Salary', direction: 'in', amount: '1500' })
  let status = ''
  await act(async () => { status = (await result.current.create({ body, tempId: 'pending-1' })).status })
  expect(status).toBe('queued')
  expect(client.getQueryData<RecurringItemOut[]>(keys.recurring.list())!.map((i) => i.name)).toEqual(['Cosmote', 'Salary'])
  expect(isPending('pending-1')).toBe(true)
})
