import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Activity } from './Activity'
import { YESTERDAY, TODAY, makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const FEED = 'GET /api/v1/transactions' as const

describe('Activity feed', () => {
  it('groups rows by day with the server net and titles rows merchant > notes > category', async () => {
    fakeApi({
      ...refRoutes(),
      [FEED]: () =>
        pageOf(
          [
            makeTxn({ merchant: 'Cosmote', amount: 38.9 }),
            makeTxn({ notes: 'Bread' }),
            makeTxn({ category_id: 'c-groc', transaction_date: YESTERDAY }),
          ],
          { day_totals: { [TODAY]: -48.9, [YESTERDAY]: -10 } },
        ),
    })
    renderActivity(<Activity />)
    const today = await screen.findByRole('region', { name: /^Today/ })
    expect(within(today).getByText('Cosmote')).toBeInTheDocument()
    expect(within(today).getByText('Bread')).toBeInTheDocument()
    const yesterday = screen.getByRole('region', { name: /^Yesterday/ })
    expect(within(yesterday).getAllByText('Groceries').length).toBeGreaterThan(0)
  })

  it('asks the API with its own names', async () => {
    const fake = fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]) })
    renderActivity(<Activity />, { route: '/activity?q=cosmote&all=1' })
    await waitFor(() => expect(fake.callsTo(FEED)).toHaveLength(1))
    const feed = fake.callsTo(FEED)[0]
    expect(feed.query.get('q')).toBe('cosmote')
    expect(feed.query.get('page_size')).toBe('50')
    expect(feed.query.get('from_date')).toBeNull()
  })

  it('hides chips at 0; No payer shows its count, toggles and clears the month', async () => {
    fakeApi({ ...refRoutes({ no_payer: 3, duplicate_groups: 0 }), [FEED]: () => pageOf([]) })
    renderActivity(<Activity />)
    const chip = await screen.findByRole('button', { name: /no payer 3/i })
    expect(screen.queryByRole('button', { name: /duplicates/i })).toBeNull()
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(chip)
    const loc = screen.getByTestId('location').textContent!
    expect(loc).toContain('missing_payer=1')
    expect(loc).not.toContain('from_date')
  })

  it('shows "No matches" with Clear filters, and "Nothing here yet" on the plain list', async () => {
    fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]) })
    renderActivity(<Activity />, { route: '/activity?q=zzz' })
    fireEvent.click(await screen.findByRole('button', { name: 'Clear filters' }))
    expect(screen.getByTestId('location').textContent).toMatch(/from_date=/)
    expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
  })

  it('loads more and keeps one header for a day split across pages', async () => {
    const first = Array.from({ length: 50 }, (_, i) => makeTxn({ notes: `row ${i}` }))
    const last = makeTxn({ notes: 'row 50' })
    fakeApi({
      ...refRoutes(),
      [FEED]: (req) =>
        req.query.get('page') === '2'
          ? pageOf([last], { total: 51, page: 2, day_totals: { [TODAY]: -510 } })
          : pageOf(first, { total: 51, day_totals: { [TODAY]: -510 } }),
    })
    renderActivity(<Activity />)
    fireEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('row 50')).toBeInTheDocument()
    expect(screen.getAllByRole('region', { name: /^Today/ })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })

  it('offline without a cached result offers the saved list', async () => {
    fakeApi(refRoutes()).down()
    setOnline(false)
    renderActivity(<Activity />, { route: '/activity?q=new-term' })
    expect(await screen.findByText('Search needs a connection')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show saved list' }))
    expect(screen.getByTestId('location').textContent).toMatch(/from_date=/)
  })
})
