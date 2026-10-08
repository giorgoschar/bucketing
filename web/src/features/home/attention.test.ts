import { expect, it } from 'vitest'
import { budgetRow, categoryUsual, day, entry, match } from '../../test/fixtures'
import { attentionReady, buildAttention, overdueWindow, type AttentionInput } from './attention'

const TODAY = '2026-10-07'
const full = (over: Partial<AttentionInput> = {}): AttentionInput => ({
  today: TODAY,
  matches: [match()],
  overdue: [
    entry({ id: 'late2', name: 'Water', overdue: true, due_date: '2026-10-03' }),
    entry({ id: 'late1', name: 'Rent', overdue: true, due_date: '2026-09-30' }),
    entry({ id: 'paid', overdue: false, status: 'done', due_date: '2026-10-01' }),
  ],
  upcoming: [
    day('2026-10-09', [entry({ id: 'est', name: 'Electricity', estimated: true, amount: 83.5 }), entry({ id: 'fixed' })], 900),
    day('2026-10-14', [entry({ id: 'novalue', name: 'Water', amount: null, due_date: '2026-10-14' })], 850),
    day('2026-10-20', [entry({ id: 'far', estimated: true, due_date: '2026-10-20' })], 800),
  ],
  budgets: [budgetRow({ pct: 75 }), budgetRow({ bucket_id: 'b2', name: 'Kids', spent: 255, budget: 300, pct: 85 }), budgetRow({ bucket_id: 'b3', budget: null, pct: null })],
  categories: [
    categoryUsual({ category_id: 'c1', name: 'A' }), categoryUsual({ category_id: 'c2', name: 'B' }),
    categoryUsual({ category_id: 'c3', name: 'C' }), categoryUsual({ category_id: 'c4', name: 'D' }),
    categoryUsual({ category_id: 'c5', name: 'E', flagged: false }),
  ],
  failed: [{ id: 7, error: 'Your wallet has less cash', createdAt: 1 }],
  ...over,
})

it('orders the attention items as the spec lists them', () => {
  expect(buildAttention(full()).map((i) => i.key)).toEqual([
    'match:m1',
    'overdue:late1', 'overdue:late2',
    'amount:est', 'amount:novalue',
    'budget:b2',
    'category:c1', 'category:c2', 'category:c3',
    'failed:7',
  ])
})

it('nothing to do is an empty list', () => {
  expect(buildAttention(full({ matches: [], overdue: [], upcoming: [], budgets: [], categories: [], failed: [] }))).toEqual([])
})

it('is ready only when every server source has data', () => {
  expect(attentionReady(full())).toBe(true)
  expect(attentionReady(full({ matches: undefined }))).toBe(false)
  expect(attentionReady(full({ categories: undefined }))).toBe(false)
})

it('the overdue window runs from the first of last month to yesterday', () => {
  expect(overdueWindow('2026-10-07')).toEqual({ from: '2026-09-01', to: '2026-10-06' })
  expect(overdueWindow('2026-01-01')).toEqual({ from: '2025-12-01', to: '2025-12-31' })
})

// Plan › Cash §4.6: the viewer's own not-yet-logged cash this month.
it('cash not logged sits after missingAmount and before budget', () => {
  const keys = buildAttention(full({ cashNotLogged: 45 })).map((i) => i.key)
  expect(keys.slice(3, 7)).toEqual(['amount:est', 'amount:novalue', 'cash', 'budget:b2'])
  expect(buildAttention(full({ cashNotLogged: 45 })).find((i) => i.kind === 'cash')).toMatchObject({ amount: 45 })
})

it.each([0.004, 0, undefined])('no cash row at %s', (cashNotLogged) => {
  expect(buildAttention(full({ cashNotLogged })).some((i) => i.kind === 'cash')).toBe(false)
})

// Plan › Pantry §4.7: "N pantry items running low", after cash and before budget.
it('pantry sits after cash and before budget', () => {
  const items = buildAttention(full({ cashNotLogged: 45, pantryLow: 3 }))
  expect(items.map((i) => i.key).slice(5, 8)).toEqual(['cash', 'pantry', 'budget:b2'])
  expect(items.find((i) => i.kind === 'pantry')).toMatchObject({ count: 3 })
})

it.each([0, undefined])('no pantry row at %s', (pantryLow) => {
  expect(buildAttention(full({ pantryLow })).some((i) => i.kind === 'pantry')).toBe(false)
})

it('the pantry summary does not hold back "All clear"', () => {
  expect(attentionReady(full({ pantryLow: undefined }))).toBe(true)
})
