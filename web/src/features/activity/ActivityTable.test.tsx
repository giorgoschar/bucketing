import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubDesktop } from '../../shell/desktopStub'
import { resetTestEnv } from '../../test/render'
import { FEED, renderDesktopActivity } from './desktopTesting'
import { makeTxn, pageOf } from './testing'

afterEach(async () => {
  vi.unstubAllGlobals()
  await resetTestEnv()
})

const ROWS = [
  makeTxn({ id: 'a', merchant: 'Lidl', amount: 12.4, category_id: 'c-groc', paid_by: 'u-maria', payment_method: 'apple_pay' }),
  makeTxn({ id: 'b', merchant: 'Cosmote', amount: 38.9 }),
  makeTxn({ id: 'c', notes: 'Bread', amount: 2 }),
]
const loc = () => screen.getByTestId('location').textContent

describe('Activity table', () => {
  it('has the seven columns and a row per payment', async () => {
    stubDesktop(true)
    renderDesktopActivity(ROWS)
    const grid = await screen.findByRole('grid', { name: 'Transactions' })
    expect(within(grid).getAllByRole('columnheader').map((h) => h.textContent))
      .toEqual(['Date', 'What', 'Category', 'Bucket', 'Paid by', 'Method', 'Amount'])
    const row = within(grid).getByRole('row', { name: /Lidl/ })
    expect(within(row).getByText(/Groceries/)).toBeInTheDocument()
    expect(within(row).getByText('Day to day')).toBeInTheDocument()
    expect(within(row).getByText('Maria')).toBeInTheDocument()
    expect(within(row).getByText('Apple Pay', { selector: '.atable__method' })).toBeInTheDocument()
    expect(within(row).getByText('−€12.40')).toBeInTheDocument()
  })

  it('stays the day-grouped list on the phone', async () => {
    renderDesktopActivity(ROWS)
    expect(await screen.findByText('Lidl')).toBeInTheDocument()
    expect(screen.queryByRole('grid')).toBeNull()
  })

  it('Date and Amount headers sort: aria-sort, ?sort= and the request', async () => {
    stubDesktop(true)
    const { fake } = renderDesktopActivity(ROWS)
    const date = await screen.findByRole('button', { name: 'Date' })
    const dateHead = screen.getByRole('columnheader', { name: 'Date' })
    const amountHead = screen.getByRole('columnheader', { name: 'Amount' })
    expect(dateHead).toHaveAttribute('aria-sort', 'descending')
    expect(amountHead).toHaveAttribute('aria-sort', 'none')
    expect(fake.callsTo(FEED)[0].query.get('sort')).toBeNull() // the default is not sent

    fireEvent.click(date)
    expect(loc()).toContain('sort=date_asc')
    expect(await screen.findByRole('columnheader', { name: 'Date' })).toHaveAttribute('aria-sort', 'ascending')
    await waitFor(() => expect(fake.callsTo(FEED).at(-1)!.query.get('sort')).toBe('date_asc'))

    fireEvent.click(await screen.findByRole('button', { name: 'Amount' }))
    expect(loc()).toContain('sort=amount_desc')
    expect(await screen.findByRole('columnheader', { name: 'Amount' })).toHaveAttribute('aria-sort', 'descending')
    await waitFor(() => expect(fake.callsTo(FEED).at(-1)!.query.get('sort')).toBe('amount_desc'))

    fireEvent.click(await screen.findByRole('button', { name: 'Amount' }))
    expect(loc()).toContain('sort=amount_asc')

    fireEvent.click(await screen.findByRole('button', { name: 'Date' }))
    expect(loc()).not.toContain('sort=')
  })

  it('reads ?sort= on a cold load and keeps the month filter when sorting', async () => {
    stubDesktop(true)
    const { fake } = renderDesktopActivity(ROWS, { route: '/activity?sort=amount_asc' })
    await screen.findByRole('grid')
    expect(screen.getByRole('columnheader', { name: 'Amount' })).toHaveAttribute('aria-sort', 'ascending')
    expect(fake.callsTo(FEED)[0].query.get('sort')).toBe('amount_asc')
    expect(fake.callsTo(FEED)[0].query.get('from_date')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cash' }))
    expect(loc()).toContain('sort=amount_asc')
    expect(loc()).toContain('payment_method=cash')
  })

  it('a phone ignores ?sort= (nothing is sent)', async () => {
    const { fake } = renderDesktopActivity(ROWS, { route: '/activity?sort=amount_asc' })
    await screen.findByText('Lidl')
    expect(fake.callsTo(FEED)[0].query.get('sort')).toBeNull()
  })

  it('keeps search, chips, totals, load more and bulk select working', async () => {
    stubDesktop(true)
    const { fake } = renderDesktopActivity(ROWS, { total: 120 })
    await screen.findByRole('grid')
    // search
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search transactions' }), { target: { value: 'lidl' } })
    await waitFor(() => expect(loc()).toContain('q=lidl'))
    // chip + totals line
    fireEvent.click(screen.getByRole('button', { name: 'Income' }))
    expect(loc()).toContain('type=income')
    // load more
    fireEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    await waitFor(() => expect(fake.callsTo(FEED).some((c) => c.query.get('page') === '2')).toBe(true))
  })

  it('bulk select uses a checkbox column', async () => {
    stubDesktop(true)
    renderDesktopActivity(ROWS)
    const grid = await screen.findByRole('grid')
    expect(within(grid).getAllByRole('columnheader')).toHaveLength(7)
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    await waitFor(() => expect(within(screen.getByRole('grid')).getAllByRole('columnheader')).toHaveLength(8))
    fireEvent.click(screen.getByRole('row', { name: /Lidl/ }))
    expect(screen.getByRole('row', { name: /Lidl/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    expect(loc()).toBe('/activity') // selecting does not open a detail
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(within(screen.getByRole('grid')).getAllByRole('columnheader')).toHaveLength(7)
  })
})

describe('Bulk actions on desktop', () => {
  it('never send the table sort to the bulk endpoint (it takes a strict filter)', async () => {
    stubDesktop(true)
    const BULK = 'POST /api/v1/transactions/bulk' as const
    const { fake } = renderDesktopActivity(ROWS, {
      route: '/activity?sort=amount_desc&missing_payer=1', total: 120,
      extra: {
        [BULK]: (req) => ({
          dry_run: (req.body as { dry_run: boolean }).dry_run, batch_id: null, matched: 120, changed: 120, unchanged: 0,
          total_out: 0, total_in: 0, skipped: [], bill: null, undo_until: null, buckets: [],
        }) as never,
      },
    })
    await screen.findByRole('grid')
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /Pick payments/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'All' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Bucket' }))
    fireEvent.change(await screen.findByLabelText('Bucket'), { target: { value: 'b-bills' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await waitFor(() => expect(fake.callsTo(BULK)).toHaveLength(1))
    const body = fake.callsTo(BULK)[0].body as { select: { filter: Record<string, unknown> } }
    expect(body.select.filter).toEqual(expect.objectContaining({ missing_payer: true }))
    expect(JSON.stringify(body)).not.toContain('sort')
    // The totals line and the counts are not sorted either.
    expect(fake.calls.filter((c) => !c.path.endsWith('/transactions') && c.query.has('sort'))).toEqual([])
  })
})

describe('Detail pane', () => {
  it('a row click opens /activity/:id beside the table, with filters kept and the row marked', async () => {
    stubDesktop(true)
    renderDesktopActivity(ROWS, { route: '/activity?payment_method=cash&sort=amount_desc' })
    fireEvent.click(await screen.findByRole('row', { name: /Cosmote/ }))
    expect(loc()).toBe('/activity/b?payment_method=cash&sort=amount_desc')
    // The detail renders in the pane and the table is still there.
    expect(await screen.findByRole('complementary', { name: 'Payment details' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Cosmote' })).toBeInTheDocument()
    expect(screen.getByRole('grid')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Cosmote/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('row', { name: /Lidl/ })).toHaveAttribute('aria-selected', 'false')
  })

  it('opens the pane from a cold /activity/:id and Back in the pane closes it', async () => {
    stubDesktop(true)
    renderDesktopActivity(ROWS, { route: '/activity/a?all=1' })
    const pane = await screen.findByRole('complementary', { name: 'Payment details' })
    expect(await screen.findByRole('row', { name: /Lidl/ })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(within(pane).getByRole('button', { name: 'Back' }))
    expect(loc()).toBe('/activity?all=1')
    expect(screen.queryByRole('complementary')).toBeNull()
  })

  it('Up and Down move between rows, Enter opens, Esc closes the pane', async () => {
    stubDesktop(true)
    const user = userEvent.setup()
    renderDesktopActivity(ROWS)
    const first = await screen.findByRole('row', { name: /Lidl/ })
    act(() => first.focus())
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('row', { name: /Cosmote/ })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('row', { name: /Bread/ })).toHaveFocus()
    await user.keyboard('{ArrowDown}') // the last row stays
    expect(screen.getByRole('row', { name: /Bread/ })).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('row', { name: /Cosmote/ })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(loc()).toMatch(/^\/activity\/b\b/)
    await screen.findByRole('complementary', { name: 'Payment details' })
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('complementary')).toBeNull())
    expect(loc()).toBe('/activity')
    expect(screen.getByRole('row', { name: /Cosmote/ })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('row', { name: /Bread/ })).toHaveFocus()
  })

  it('on the phone /activity/:id is the full-screen detail, no table', async () => {
    renderDesktopActivity(ROWS, { route: '/activity/a' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Lidl' })).toBeInTheDocument()
    expect(screen.queryByRole('grid')).toBeNull()
    expect(screen.queryByRole('complementary')).toBeNull()
  })

  it('opening and closing a row keeps the same table: its rows are the same elements, with page 2 still loaded', async () => {
    stubDesktop(true)
    const first = Array.from({ length: 50 }, (_, i) => makeTxn({ id: `r${i}`, notes: `row ${i}` }))
    const fakeRows = [...first, makeTxn({ id: 'r50', notes: 'row 50' })]
    renderDesktopActivity(first, {
      extra: {
        [FEED]: (req) => (req.query.get('page') === '2'
          ? pageOf([fakeRows[50]], { total: 51, page: 2 })
          : pageOf(first, { total: 51 })),
      },
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    const row = await screen.findByRole('row', { name: /row 50/ })
    fireEvent.click(row)
    await screen.findByRole('complementary', { name: 'Payment details' })
    expect(screen.getByRole('row', { name: /row 50/ })).toBe(row) // not unmounted and mounted again
    fireEvent.click(within(screen.getByRole('complementary')).getByRole('button', { name: 'Back' }))
    await waitFor(() => expect(screen.queryByRole('complementary')).toBeNull())
    expect(screen.getByRole('row', { name: /row 50/ })).toBe(row)
    expect(row).toHaveFocus() // the pane's close puts focus back on the row that was open
  })
})
