import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, reply } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { formatShortDate } from '../../../ui/format'
import { BillHistoryView } from './BillHistory'
import { change, history, point } from './fixtures'
import type { ItemHistoryOut } from './types'
import { billsRoutes } from './fixtures'
import { keys } from '../../../data/keys'

beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-10-09T12:00:00')) })
afterEach(resetTestEnv)

const HISTORY = 'GET /api/v1/recurring/{item_id}/history'
const USAGE = 'PUT /api/v1/recurring/entries/{entry_id}/usage'
const serve = (h: ItemHistoryOut, extra: Record<string, unknown> = {}) =>
  fakeApi(billsRoutes([], { [HISTORY]: () => h, ...extra }))

const P = (due_date: string, amount: number, usage: number | null = null, over = {}) =>
  point({ entry_id: `e-${due_date}`, due_date, amount, usage, unit_price: usage ? Math.round((amount / usage) * 1e4) / 1e4 : null, ...over })

const FULL = history({
  points: [
    P('2025-01-14', 80, 400), P('2025-10-14', 40, 200), P('2026-01-14', 84, 410), P('2026-08-14', 61, 300),
    P('2026-09-14', 70, 330, { transaction_id: 't1' }),
  ],
})

const d = (iso: string) => `${formatShortDate(iso)} ${iso.slice(0, 4)}`
const render = (id = 'i1') => renderWithProviders(<BillHistoryView id={id} />, { route: `/insights/bills/${id}` })

it('the header names the item and the tiles show Last, Usual, 12 months and Average', async () => {
  serve(FULL)
  render()
  expect(await screen.findByRole('heading', { name: 'Electricity' })).toBeInTheDocument()
  const tiles = screen.getByRole('group', { name: 'Summary' })
  expect(within(tiles).getByText('Last').nextSibling).toHaveTextContent('€70.00')
  // no change: the median of the last 3 (84, 61, 70) is 70
  expect(within(tiles).getByText('Usual').nextSibling).toHaveTextContent('€70.00')
  // Nov 2025 .. Oct 2026: 84 + 61 + 70
  expect(within(tiles).getByText('12 months').nextSibling).toHaveTextContent('€215.00')
  expect(within(tiles).getByText('Average').nextSibling).toHaveTextContent('€71.67')
})

it('Usual is the server figure when there is a change', async () => {
  serve({ ...FULL, change: change({ usual: 61 }) })
  render()
  const tiles = await screen.findByRole('group', { name: 'Summary' })
  expect(within(tiles).getByText('Usual').nextSibling).toHaveTextContent('€61.00')
})

it.each([
  [change({ basis: 'last_year', reason: 'usage', reason_pct: 30 }), 'Electricity was €84, usually €61. Same month last year: €61. You used 30% more kWh.'],
  [change({ basis: 'recent', reason: 'price', reason_pct: -12 }), 'Electricity was €84, usually €61. Usual from the last 3 payments: €61. The price per kWh went down 12%.'],
  [change({ basis: 'recent' }), 'Electricity was €84, usually €61. Usual from the last 3 payments: €61.'],
])('the change note is the notification sentence (%#)', async (c, sentence) => {
  serve({ ...FULL, change: c })
  render()
  expect(await screen.findByRole('note')).toHaveTextContent(sentence)
})

it('no change: no note', async () => {
  serve(FULL)
  render()
  await screen.findByRole('heading', { name: 'Electricity' })
  expect(screen.queryByRole('note')).toBeNull()
})

it('the year picker starts on the latest year and steps back, stopping at the first year with entries', async () => {
  serve(FULL)
  render()
  await screen.findByRole('heading', { name: 'Electricity' })
  expect(screen.getByText('2026', { selector: '.billhist__yearlabel' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next year' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Previous year' }))
  expect(screen.getByText('2025', { selector: '.billhist__yearlabel' })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /Amount by month, 2025/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Previous year' })).toBeDisabled()
})

it('last-year bars are drawn only for months that have a month a year earlier', async () => {
  serve(FULL)
  render()
  const chart = await screen.findByRole('img', { name: /Amount by month, 2026/ })
  expect([...chart.querySelectorAll('[data-kind="year"]')].map((b) => b.getAttribute('data-month'))).toEqual(['1', '8', '9'])
  // Jan and Oct 2025 exist; Aug and Sep 2025 do not (October's bar stands alone: nothing paid yet this year)
  expect([...chart.querySelectorAll('[data-kind="last-year"]')].map((b) => b.getAttribute('data-month'))).toEqual(['1', '10'])
})

it('the unit-price and usage charts show with two or more points that have usage, and are hidden otherwise', async () => {
  serve(FULL)
  const { unmount } = render()
  expect(await screen.findByRole('img', { name: /Price per kWh by month, 2026/ })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /Usage by month, 2026/ })).toBeInTheDocument()
  unmount()
  serve({ ...FULL, points: [P('2026-08-14', 61), P('2026-09-14', 70, 330)] })
  render()
  await screen.findByRole('img', { name: /Amount by month/ })
  expect(screen.queryByRole('img', { name: /Price per kWh/ })).toBeNull()
  expect(screen.queryByRole('img', { name: /Usage by month/ })).toBeNull()
})

it('the table is newest first with against last year in € and %, "—" where there is no month to compare', async () => {
  serve(FULL)
  render()
  const table = await screen.findByRole('table', { name: 'Electricity history' })
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows).toHaveLength(5)
  expect(rows[0]).toHaveTextContent(d('2026-09-14'))
  expect(rows[0]).toHaveTextContent('€70.00')
  expect(rows[0]).toHaveTextContent('330 kWh')
  expect(rows[0]).toHaveTextContent('€0.2121')
  expect(rows[0]).toHaveTextContent('—') // no Sep 2025
  expect(rows[2]).toHaveTextContent(d('2026-01-14'))
  expect(rows[2]).toHaveTextContent('+€4.00 (+5%)')
  expect(rows[4]).toHaveTextContent(d('2025-01-14'))
  expect(within(rows[0]).getByRole('link', { name: d('2026-09-14') })).toHaveAttribute('href', '/activity/t1')
  expect(within(rows[1]).queryByRole('link')).toBeNull()
})

it('an item without a unit has no usage columns, no charts for it and no Edit usage', async () => {
  serve({ ...FULL, item: { ...FULL.item, usage_unit: null }, points: [P('2026-08-14', 61), P('2026-09-14', 70)] })
  render()
  const table = await screen.findByRole('table', { name: 'Electricity history' })
  expect(within(table).queryByRole('columnheader', { name: 'Usage' })).toBeNull()
  expect(screen.queryByRole('button', { name: /Edit usage/ })).toBeNull()
})

it('fewer than 2 entries: the charts give way to one sentence', async () => {
  serve({ ...FULL, points: [P('2026-09-14', 70, 330)] })
  render()
  expect(await screen.findByText('Not enough history yet. It fills in as you pay this bill.')).toBeInTheDocument()
  expect(screen.queryByRole('img')).toBeNull()
})

it('Edit usage opens a small sheet and saves with PUT; clearing sends null', async () => {
  const fake = serve(FULL, { [USAGE]: () => ({}) })
  render()
  await screen.findByRole('table', { name: 'Electricity history' })
  fireEvent.click(screen.getByRole('button', { name: `Edit usage, ${d('2026-09-14')}` }))
  const sheet = screen.getByRole('dialog', { name: 'Edit usage' })
  const input = within(sheet).getByLabelText('Usage (kWh)')
  expect(input).toHaveValue('330')
  fireEvent.change(input, { target: { value: '412,5' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save usage' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(fake.callsTo(USAGE as never)).toMatchObject([{ path: '/api/v1/recurring/entries/e-2026-09-14/usage', body: { usage: 412.5 } }])

  fireEvent.click(screen.getByRole('button', { name: `Edit usage, ${d('2026-09-14')}` }))
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save usage' }))
  await waitFor(() => expect(fake.callsTo(USAGE as never)).toHaveLength(2))
  expect(fake.callsTo(USAGE as never)[1].body).toEqual({ usage: null })
})

it('a rejected usage keeps the sheet open', async () => {
  serve(FULL, { [USAGE]: () => reply(422, { detail: 'Usage is too large.' }) })
  render()
  await screen.findByRole('table', { name: 'Electricity history' })
  fireEvent.click(screen.getByRole('button', { name: `Edit usage, ${d('2026-09-14')}` }))
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save usage' }))
  expect(await screen.findAllByText('Usage is too large.')).not.toHaveLength(0)
  expect(screen.getByRole('dialog', { name: 'Edit usage' })).toBeInTheDocument()
})

it('bad usage text blocks Save usage', async () => {
  serve(FULL)
  render()
  await screen.findByRole('table', { name: 'Electricity history' })
  fireEvent.click(screen.getByRole('button', { name: `Edit usage, ${d('2026-09-14')}` }))
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: 'lots' } })
  expect(screen.getByRole('button', { name: 'Save usage' })).toBeDisabled()
})

it('offline with a saved copy: the banner, and Edit usage disabled with "Connect to change usage"', async () => {
  const fake = serve(FULL)
  const { unmount, client } = render()
  await screen.findByRole('table', { name: 'Electricity history' })
  unmount()
  setOnline(false)
  fake.down()
  renderWithProviders(<BillHistoryView id="i1" />, { client })
  expect(await screen.findByText('Offline · showing saved history')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /Edit usage/ })[0]).toBeDisabled()
  expect(screen.getByText('Connect to change usage')).toBeInTheDocument()
})

it('Edit usage disables live when the device goes offline with its sheet open', async () => {
  serve(FULL)
  render()
  await screen.findByRole('table', { name: 'Electricity history' })
  fireEvent.click(screen.getByRole('button', { name: `Edit usage, ${d('2026-09-14')}` }))
  act(() => setOnline(false))
  expect(screen.getByRole('button', { name: 'Save usage' })).toBeDisabled()
  expect(within(screen.getByRole('dialog')).getByText('Connect to change usage')).toBeInTheDocument()
})

it('offline with nothing saved: an empty state', async () => {
  setOnline(false)
  serve(FULL).down()
  render()
  expect(await screen.findByText('No saved history yet. Connect once to load it.')).toBeInTheDocument()
})


// ---- Fix round 1 ----

it('F3: the unit-price axis starts at its minimum, not at 0, and the labels do not collide', async () => {
  serve(FULL)
  render()
  const chart = await screen.findByRole('img', { name: /Price per kWh by month, 2026/ })
  const labels = [...chart.querySelectorAll('text')].map((t) => t.textContent)
  expect(labels).not.toContain('€0.000')
  // lowest price in 2026: 61/300 = 0.2033
  expect(labels).toContain('€0.203')
  expect(labels.filter((l) => l === '€0.203')).toHaveLength(1)
})

it('F6: axis labels are short: whole euros for amounts and bare numbers for usage', async () => {
  serve({ ...FULL, points: [P('2026-08-14', 1200, 400), P('2026-09-14', 70, 330)] })
  render()
  const amount = await screen.findByRole('img', { name: /Amount by month, 2026/ })
  expect([...amount.querySelectorAll('text')].map((t) => t.textContent)).toContain('€1,200')
  const usage = screen.getByRole('img', { name: /Usage by month, 2026/ })
  const texts = [...usage.querySelectorAll('text')].map((t) => t.textContent ?? '')
  expect(texts.some((t) => t.includes('kWh'))).toBe(false)
  expect(screen.getByRole('heading', { name: 'Usage (kWh)' })).toBeInTheDocument()
})

it('F4: Edit usage also refreshes the Plan and Home entries that carry usage', async () => {
  serve(FULL, { [USAGE]: () => ({}) })
  const { client } = render()
  await screen.findByRole('table', { name: 'Electricity history' })
  client.setQueryData([...keys.plan.all, 'upcoming', 30], [])
  client.setQueryData([...keys.home.all, 'overdue', 'a', 'b'], [])
  fireEvent.click(screen.getByRole('button', { name: `Edit usage, ${d('2026-09-14')}` }))
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: '400' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save usage' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(client.getQueryState([...keys.plan.all, 'upcoming', 30])?.isInvalidated).toBe(true)
  expect(client.getQueryState([...keys.home.all, 'overdue', 'a', 'b'])?.isInvalidated).toBe(true)
})

it('F10: an item with no unit still shows the usage it once had', async () => {
  serve({ ...FULL, item: { ...FULL.item, usage_unit: null } })
  render()
  const table = await screen.findByRole('table', { name: 'Electricity history' })
  expect(within(table).getByRole('columnheader', { name: 'Usage' })).toBeInTheDocument()
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent('330')
  expect(screen.queryByRole('button', { name: /Edit usage/ })).toBeNull()
})

it('F11: the summary is a group around the list, the Last tile separates amount and date, the year is announced', async () => {
  serve(FULL)
  render()
  const group = await screen.findByRole('group', { name: 'Summary' })
  expect(group.tagName).toBe('DIV')
  expect(group.querySelector('dl')).not.toBeNull()
  const lastDd = within(group).getByText('Last').nextSibling as HTMLElement
  expect(lastDd.querySelectorAll('dd, span').length).toBeGreaterThan(0)
  expect(lastDd.textContent).toMatch(/€70\.00[,\s]/)
  expect(screen.getByText('2026', { selector: '.billhist__yearlabel' })).toHaveAttribute('aria-live', 'polite')
})

it('F12: the last-year bars have an outline so they do not rely on a pale fill', async () => {
  serve(FULL)
  render()
  const chart = await screen.findByRole('img', { name: /Amount by month, 2026/ })
  const bar = chart.querySelector('[data-kind="last-year"]') as SVGElement
  expect(bar.getAttribute('style')).toMatch(/stroke:\s*var\(--c1\)/)
})

it('F14: the scope note is one sentence', async () => {
  serve(FULL)
  render()
  expect(await screen.findByText('Bills cover all time. The lens and period do not apply.')).toBeInTheDocument()
})
