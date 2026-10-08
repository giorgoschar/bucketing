import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../../data/keys'
import { markPending } from '../../../data/pending'
import { fakeApi, type Routes } from '../../../test/fakeApi'
import { entry, item, page, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, testQueryClient } from '../../../test/render'
import { emptyItemForm, formToBody, pendingItem } from './form'
import { Items } from './Items'

afterEach(resetTestEnv)

const list = [
  item(),
  item({
    id: 'i2', name: 'Salary', direction: 'in', amount: 1500, rule_day: 26, rule_adjust: 'previous_business_day',
    next_entry: entry({ id: 'e2', item_id: 'i2', name: 'Salary', direction: 'in', due_date: '2026-10-26', amount: 1500 }),
  }),
  item({ id: 'i3', name: 'Gym', is_active: false, next_entry: null }),
  item({ id: 'i4', name: 'Electricity', amount: null, rule_kind: 'last_business_day', rule_day: null,
    next_entry: entry({ id: 'e4', item_id: 'i4', name: 'Electricity', due_date: '2026-10-30', amount: null }) }),
]
const routes = (): Routes => ({
  ...readRoutes(),
  'GET /api/v1/recurring': () => list,
  'GET /api/v1/transactions': () => page([]),
  'POST /api/v1/recurring/preview': () => ({ dates: [] }),
})
const titles = (group: HTMLElement) =>
  Array.from(group.querySelectorAll('.ui-row__title')).map((t) => t.textContent)

it('groups In and Out, with the schedule, next date and amount; paused items last', async () => {
  fakeApi(routes())
  renderWithProviders(<Items />, { route: '/plan/items' })
  const inGroup = await screen.findByRole('region', { name: 'In' })
  const outGroup = screen.getByRole('region', { name: 'Out' })
  expect(titles(inGroup)).toEqual(['Salary'])
  expect(titles(outGroup)).toEqual(['Cosmote', 'Electricity', 'Gym'])
  expect(within(inGroup).getByRole('button', { name: /Salary/ })).toHaveTextContent('26th, or the business day before · next 26 Oct')
  expect(within(outGroup).getByRole('button', { name: /Electricity/ })).toHaveTextContent('Last business day · next 30 Oct')
  expect(within(outGroup).getByRole('button', { name: /Electricity/ })).toHaveTextContent('variable')
  expect(within(outGroup).getByRole('button', { name: /Gym/ })).toHaveTextContent('Paused')
})

it('tapping a row opens the Item sheet for it; ＋ and ?new=1 open a new one', async () => {
  fakeApi(routes())
  const { router } = renderWithProviders(<Items />, { route: '/plan/items' })
  fireEvent.click(await screen.findByRole('button', { name: /Cosmote/ }))
  expect(screen.getByRole('dialog', { name: 'Edit item' })).toBeInTheDocument()
  expect(screen.getByLabelText('Name')).toHaveValue('Cosmote')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: 'New item' }))
  expect(screen.getByRole('dialog', { name: 'New item' })).toBeInTheDocument()
  expect(router.state.location.search).toBe('?new=1')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(router.state.location.search).toBe('')
})

it('opens a new item straight from /plan/items?new=1', () => {
  fakeApi(routes())
  renderWithProviders(<Items />, { route: '/plan/items?new=1' })
  expect(screen.getByRole('dialog', { name: 'New item' })).toBeInTheDocument()
})

it('an item created offline shows as waiting to sync and cannot be opened yet', async () => {
  fakeApi(routes())
  const client = testQueryClient()
  const queued = pendingItem(formToBody({ ...emptyItemForm('2026-10-07', 'u1'), name: 'Cleaner' }), 'pending-1')
  client.setQueryData(keys.recurring.list(), [item(), queued])
  act(() => markPending('pending-1'))
  renderWithProviders(<Items />, { route: '/plan/items', client })
  const row = (await screen.findByText('Cleaner')).closest('.ui-row')!
  expect(row).toHaveTextContent('Waiting to sync')
  expect(row.tagName).toBe('DIV')
})

it('the next entry in the Item sheet opens the Entry sheet', async () => {
  fakeApi(routes())
  renderWithProviders(<Items />, { route: '/plan/items' })
  fireEvent.click(await screen.findByRole('button', { name: /Cosmote/ }))
  fireEvent.click(screen.getByRole('button', { name: /Next: 9 Oct/ }))
  expect(screen.getByRole('dialog', { name: 'Cosmote' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Edit item' })).toBeNull()
})
