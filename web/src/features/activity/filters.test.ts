
import { describe, expect, it } from 'vitest'
import { activeFilterCount, type FeedState, fromSearch, monthLabel, toQuery, toSearch } from './filters'

const TODAY = new Date(2026, 9, 7) // 7 Oct 2026
const OCT = { from_date: '2026-10-01', to_date: '2026-10-31' }

describe('filters', () => {
  it.each<FeedState>([
    { filter: { ...OCT }, dups: false },
    { filter: {}, dups: false }, // All time
    { filter: {}, dups: true },
    { filter: { q: 'cosmote', missing_payer: true }, dups: false },
    {
      filter: {
        type: 'expense', category_id: 'c', bucket_id: 'b', paid_by: 'u', payment_method: 'cash',
        recurring_bill_id: 'r', from_date: '2026-09-01', to_date: '2026-09-15', min_amount: '10', max_amount: '99.5',
      },
      dups: false,
    },
    { filter: { no_bucket: true, fixed: true }, dups: false },
  ])('round-trips %j through the URL', (state) => {
    expect(fromSearch(toSearch(state), TODAY)).toEqual(state)
  })

  it('opens plain /activity on this month', () => {
    expect(fromSearch(new URLSearchParams(''), TODAY)).toEqual({ filter: OCT, dups: false })
  })

  it('treats a deep link with its own filter as all time', () => {
    expect(fromSearch(new URLSearchParams('recurring_bill_id=r1'), TODAY).filter).toEqual({ recurring_bill_id: 'r1' })
  })

  it('drops unknown enum values and blanks', () => {
    expect(fromSearch(new URLSearchParams('type=bogus&q=%20&all=1'), TODAY).filter).toEqual({})
  })

  it('sends the API names, flags as true', () => {
    expect(toQuery({ q: 'x', missing_payer: true, ...OCT })).toEqual({ q: 'x', missing_payer: true, ...OCT })
  })

  it('counts Filters-sheet fields, not the month or the search', () => {
    expect(activeFilterCount({ q: 'x', ...OCT })).toBe(0)
    expect(activeFilterCount({ type: 'income', min_amount: '5', max_amount: '9', from_date: '2026-09-03' })).toBe(3)
    expect(monthLabel(OCT)).toBe('Oct 2026')
    expect(monthLabel({})).toBe('All time')
  })
})
