import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { setIdentity } from '../offline/identity'
import { fakeApi } from '../test/fakeApi'
import { bucket, household, item, member } from '../test/fixtures'
import { Providers, resetTestEnv, TEST_IDENTITY, testQueryClient } from '../test/render'
import { memberName, toCategories, toTransactionPage, useBuckets, useHousehold, useRecurringItems } from './reads'

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

const wrapper = ({ children }: { children: ReactNode }) => <Providers client={testQueryClient()}>{children}</Providers>

it('useHousehold narrows the untyped dict; missing members become []', async () => {
  fakeApi({ 'GET /api/v1/settings/household': () => ({ id: 'h1', name: 'Home', default_currency: 'EUR' }) })
  const { result } = renderHook(() => useHousehold(), { wrapper })
  await waitFor(() => expect(result.current.data).toEqual({ id: 'h1', name: 'Home', default_currency: 'EUR', members: [] }))
})

it('useRecurringItems and useBuckets return the lists', async () => {
  fakeApi({ 'GET /api/v1/recurring': () => [item()], 'GET /api/v1/buckets': () => [{ ...bucket(), balance: {} }] })
  const items = renderHook(() => useRecurringItems(), { wrapper })
  const buckets = renderHook(() => useBuckets(), { wrapper })
  await waitFor(() => expect(items.result.current.data).toEqual([item()]))
  await waitFor(() => expect(buckets.result.current.data).toEqual([bucket()]))
})

it('memberName falls back from display name to username', () => {
  expect(memberName(member())).toBe('Giorgos')
  expect(memberName(member({ display_name: null }))).toBe('giorgos')
  expect(memberName(member({ display_name: null, username: null }))).toBe('Member')
  expect(household().members).toHaveLength(2)
})

it('toTransactionPage coerces numeric strings and drops nothing', () => {
  const p = toTransactionPage({ total: '2', page: 1, page_size: 10, items: [{ id: 't1', type: 'income', amount: '2450.00', currency: 'EUR', transaction_date: '2026-10-01' }] })
  expect(p.total).toBe(2)
  expect(p.items[0]).toMatchObject({ id: 't1', type: 'income', amount: 2450, merchant: null, bucket_id: null })
})

it('toCategories keeps the Settings fields and defaults them when missing', () => {
  const [full, bare] = toCategories([
    { id: 'c1', name: 'Fuel', system_key: 'fuel', is_default: true, locked: true, expense_count: 12, rule_count: '3' },
    { id: 'c2', name: 'Coffee' },
  ])
  expect(full).toMatchObject({ is_default: true, system_key: 'fuel', locked: true, expense_count: 12, rule_count: 3 })
  expect(bare).toMatchObject({ is_default: false, system_key: null, locked: false, expense_count: 0, rule_count: 0 })
})
