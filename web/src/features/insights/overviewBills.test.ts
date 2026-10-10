import { expect, it } from 'vitest'
import { makeInsights } from './fixtures'
import { visibleWidgets } from './overview'

const THIS = { preset: 'this_month' } as const

it('the Bills card sits right after Vs usual when asked for', () => {
  expect(visibleWidgets(makeInsights(), { lens: 'household', period: THIS, bills: true })).toEqual([
    'headline', 'onTrack', 'inOut', 'where', 'inOutMonths', 'trend', 'biggest', 'method', 'budgets', 'savings', 'vsUsual', 'bills', 'fuel',
  ])
})

it('without a Vs usual card (a member lens) it follows Savings', () => {
  expect(visibleWidgets(makeInsights(), { lens: 'm', period: THIS, bills: true }).slice(-3)).toEqual(['savings', 'bills', 'fuel'])
})

it('the Bills card and panel stay in an empty period (a bill is the household\'s, whatever the period)', () => {
  const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0 } })
  expect(visibleWidgets(empty, { lens: 'household', period: THIS, bills: true })).toEqual(['headline', 'empty', 'bills'])
  expect(visibleWidgets(empty, { lens: 'household', period: THIS, bills: true, desktop: true })).toEqual(['headline', 'empty', 'billsPanel'])
  expect(visibleWidgets(empty, { lens: 'household', period: THIS })).toEqual(['headline', 'empty'])
})

// ---- Phase B: the Statements card follows the Bills card (spec §4.4)

it('the Statements card follows the Bills card when asked for, and in an empty period too', () => {
  const opts = { lens: 'household', period: THIS, bills: true, statements: true } as const
  expect(visibleWidgets(makeInsights(), opts).slice(-3)).toEqual(['bills', 'statements', 'fuel'])
  const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0 } })
  expect(visibleWidgets(empty, opts)).toEqual(['headline', 'empty', 'bills', 'statements'])
  expect(visibleWidgets(empty, { ...opts, desktop: true })).toEqual(['headline', 'empty', 'billsPanel', 'statements'])
  expect(visibleWidgets(makeInsights(), { lens: 'household', period: THIS, bills: true })).not.toContain('statements')
})
