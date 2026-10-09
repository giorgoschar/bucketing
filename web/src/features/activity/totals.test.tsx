import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Activity } from './Activity'
import { isFiltered, monthRange } from './filters'
import { HOLD_MS, _resetHeldForTests } from './heldDeletes'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'
import type { TransactionTotals } from './totalsTypes'

afterEach(async () => {
  _resetHeldForTests()
  await resetTestEnv()
})

const TOTALS = 'GET /api/v1/transactions/totals' as const
const FEED = 'GET /api/v1/transactions' as const
/** The line is split into spans (the figures are .ui-num): match on the whole paragraph's text. */
const line = (text: string | RegExp) => (_: string, el: Element | null) =>
  !!el?.classList.contains('activity__total') && (typeof text === 'string' ? el.textContent === text : text.test(el.textContent ?? ''))
const T = (over: Partial<TransactionTotals> = {}): TransactionTotals => ({ count: 23, out: 412.3, in: 0, ...over })

describe('isFiltered', () => {
  const today = new Date(2026, 9, 8)
  it('the default (this month) and plain All time are not filtered', () => {
    expect(isFiltered(monthRange(today), today)).toBe(false)
    expect(isFiltered({}, today)).toBe(false)
  })
  it('search, any chip, another month or custom dates are', () => {
    expect(isFiltered({ ...monthRange(today), q: 'cosmote' }, today)).toBe(true)
    expect(isFiltered({ missing_payer: true }, today)).toBe(true)
    expect(isFiltered({ ...monthRange(today), type: 'income' }, today)).toBe(true)
    expect(isFiltered(monthRange(new Date(2026, 8, 1)), today)).toBe(true)
    expect(isFiltered({ from_date: '2026-10-02', to_date: '2026-10-05' }, today)).toBe(true)
  })
})

describe('Activity filter total', () => {
  it('is hidden, and never asked for, when nothing is filtered', async () => {
    const fake = fakeApi({ ...refRoutes(), [FEED]: () => pageOf([makeTxn({ merchant: 'Cosmote' })]), [TOTALS]: () => T() })
    renderActivity(<Activity />)
    expect(await screen.findByText('Cosmote')).toBeInTheDocument()
    expect(screen.queryByText(line(/entries ·/))).toBeNull()
    expect(fake.callsTo(TOTALS)).toHaveLength(0)
  })

  it('shows one quiet line "{count} entries · Out €X · In €Y" over all matches, with the feed filter', async () => {
    const fake = fakeApi({ ...refRoutes(), [FEED]: () => pageOf([makeTxn({ merchant: 'Cosmote' })]), [TOTALS]: () => T({ in: 1500 }) })
    renderActivity(<Activity />, { route: '/activity?q=cosmote&type=expense&all=1' })
    const el = await screen.findByText(line('23 entries · Out €412.30 · In €1,500.00'))
    expect(el).toHaveClass('activity__total')
    expect([...el.querySelectorAll('.ui-num')].map((e) => e.textContent)).toEqual(['23', '€412.30', '€1,500.00'])
    expect(el).toHaveAttribute('role', 'status')
    const call = fake.callsTo(TOTALS)[0]
    expect(call.query.get('q')).toBe('cosmote')
    expect(call.query.get('type')).toBe('expense')
    expect(call.query.get('page')).toBeNull()
  })

  it('says "1 entry" for one match', async () => {
    fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]), [TOTALS]: () => T({ count: 1, out: 9.5 }) })
    renderActivity(<Activity />, { route: '/activity?missing_payer=1' })
    expect(await screen.findByText(line('1 entry · Out €9.50 · In €0.00'))).toBeInTheDocument()
  })

  it('goes away when the filter is cleared back to this month', async () => {
    fakeApi({ ...refRoutes({ no_payer: 2, duplicate_groups: 0 }), [FEED]: () => pageOf([]), [TOTALS]: () => T() })
    renderActivity(<Activity />, { route: '/activity?missing_payer=1' })
    expect(await screen.findByText(line(/^23 entries/))).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /no payer/i }))
    await waitFor(() => expect(screen.queryByText(line(/^23 entries/))).toBeNull())
  })

  it('offline with nothing saved shows nothing (no spinner, no error)', async () => {
    fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]), [TOTALS]: () => T() }).down()
    setOnline(false)
    renderActivity(<Activity />, { route: '/activity?q=x&all=1' })
    expect(await screen.findByText('Search needs a connection')).toBeInTheDocument()
    expect(screen.queryByText(line(/entries ·/))).toBeNull()
  })

  it('offline it shows the saved total from the device cache', async () => {
    const fake = fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]), [TOTALS]: () => T() })
    const first = renderActivity(<Activity />, { route: '/activity?q=x&all=1' })
    expect(await screen.findByText(line(/^23 entries/))).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 50)) // the encrypted cache write settles
    first.unmount()
    fake.down()
    setOnline(false)
    renderActivity(<Activity />, { route: '/activity?q=x&all=1' }) // a fresh query client: only the device cache
    expect(await screen.findByText(line('23 entries · Out €412.30 · In €0.00'))).toBeInTheDocument()
  })

  it('a failed totals call shows nothing', async () => {
    fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]), [TOTALS]: () => new Response(null, { status: 500 }) })
    renderActivity(<Activity />, { route: '/activity?q=x&all=1' })
    expect(await screen.findByText('No matches')).toBeInTheDocument()
    expect(screen.queryByText(line(/entries ·/))).toBeNull()
  })

  it('refreshes after a swipe delete', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const row = makeTxn({ merchant: 'Cosmote', amount: 38.9 })
    let deleted = false
    fakeApi({
      ...refRoutes(),
      [FEED]: () => pageOf(deleted ? [] : [row]),
      [TOTALS]: () => (deleted ? T({ count: 0, out: 0 }) : T({ count: 1, out: 38.9 })),
      'DELETE /api/v1/transactions/{txn_id}': () => { deleted = true; return null },
    })
    renderActivity(<Activity />, { route: '/activity?q=cosmote&all=1' })
    expect(await screen.findByText(line('1 entry · Out €38.90 · In €0.00'))).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    act(() => vi.advanceTimersByTime(HOLD_MS))
    expect(await screen.findByText(line('0 entries · Out €0.00 · In €0.00'))).toBeInTheDocument()
  })

  it('refreshes after a bulk change', async () => {
    const row = makeTxn({ notes: 'one' })
    let applied = false
    fakeApi({
      ...refRoutes(),
      [FEED]: () => pageOf([row]),
      [TOTALS]: () => (applied ? T({ count: 1, out: 0, in: 10 }) : T({ count: 1, out: 10 })),
      'POST /api/v1/transactions/bulk': (req) => {
        const dry = (req.body as { dry_run: boolean }).dry_run
        if (!dry) applied = true
        return {
          dry_run: dry, batch_id: 'b9', matched: 1, changed: 1, unchanged: 0, total_out: 10, total_in: 0,
          skipped: [], bill: null, undo_until: null, buckets: [],
        } as never
      },
    })
    renderActivity(<Activity />, { route: '/activity?q=one&all=1' })
    expect(await screen.findByText(line('1 entry · Out €10.00 · In €0.00'))).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    fireEvent.click(screen.getByRole('button', { name: 'Bucket' }))
    fireEvent.change(await screen.findByLabelText('Bucket'), { target: { value: 'b-bills' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 1' }))
    expect(await screen.findByText(line('1 entry · Out €0.00 · In €10.00'))).toBeInTheDocument()
  })
})
