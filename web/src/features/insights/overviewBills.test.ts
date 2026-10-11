import { expect, it } from 'vitest'
import { makeInsights } from './fixtures'
import { visibleWidgets } from './overview'

const THIS = { preset: 'this_month' } as const

// Phase C §2.2: Bills and Statements moved to their own tab (the old tests asked where they sat among the cards).
it('the Bills tab holds the Bills card, or the panel on desktop', () => {
  expect(visibleWidgets(makeInsights(), { tab: 'bills', lens: 'household', period: THIS, bills: true })).toEqual(['bills'])
  expect(visibleWidgets(makeInsights(), { tab: 'bills', lens: 'household', period: THIS, bills: true, desktop: true })).toEqual(['billsPanel'])
  expect(visibleWidgets(makeInsights(), { tab: 'bills', lens: 'm', period: THIS, bills: true })).toEqual(['bills'])
})

it('the Bills card and panel stay in an empty period (a bill is the household\'s, whatever the period)', () => {
  const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0 } })
  expect(visibleWidgets(empty, { tab: 'bills', lens: 'household', period: THIS, bills: true })).toEqual(['bills'])
  expect(visibleWidgets(empty, { tab: 'bills', lens: 'household', period: THIS, bills: true, desktop: true })).toEqual(['billsPanel'])
  expect(visibleWidgets(empty, { lens: 'household', period: THIS, bills: true })).toEqual(['summary', 'empty'])
})

it('the Statements card follows the Bills card when asked for, and in an empty period too', () => {
  const opts = { tab: 'bills', lens: 'household', period: THIS, bills: true, statements: true } as const
  expect(visibleWidgets(makeInsights(), opts)).toEqual(['bills', 'statements'])
  const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0 } })
  expect(visibleWidgets(empty, opts)).toEqual(['bills', 'statements'])
  expect(visibleWidgets(empty, { ...opts, desktop: true })).toEqual(['billsPanel', 'statements'])
  expect(visibleWidgets(makeInsights(), { ...opts, statements: false })).not.toContain('statements')
})

it('no other tab carries Bills or Statements', () => {
  for (const tab of ['overview', 'trends'] as const) {
    const ids = visibleWidgets(makeInsights(), { tab, lens: 'household', period: THIS, bills: true, statements: true, desktop: true })
    expect(ids).not.toContain('bills')
    expect(ids).not.toContain('billsPanel')
    expect(ids).not.toContain('statements')
  }
})
