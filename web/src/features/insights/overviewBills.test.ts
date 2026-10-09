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
