import { describe, expect, it } from 'vitest'
import { makeInsights } from './fixtures'
import { deltaText, paidOutSentence, visibleWidgets } from './overview'

const THIS = { preset: 'this_month' } as const

describe('visibleWidgets', () => {
  it('is the fixed order for the household this month', () => {
    expect(visibleWidgets(makeInsights(), { lens: 'household', period: THIS })).toEqual([
      'headline', 'onTrack', 'inOut', 'where', 'inOutMonths', 'trend', 'biggest', 'method', 'budgets', 'savings', 'vsUsual', 'fuel',
    ])
  })
  it('a member lens adds identity and share and hides the household-only widgets', () => {
    expect(visibleWidgets(makeInsights(), { lens: 'm', period: THIS })).toEqual([
      'identity', 'headline', 'share', 'inOut', 'where', 'inOutMonths', 'trend', 'biggest', 'method', 'budgets', 'savings', 'fuel',
    ])
  })
  it('hides widgets on null data and On track outside this month', () => {
    const d = makeInsights({ fuel: null, kpis: { ...makeInsights().kpis, savings_rate: null, largest: null } })
    const ids = visibleWidgets(d, { lens: 'household', period: { preset: 'last_3m' } })
    expect(ids).not.toContain('fuel')
    expect(ids).not.toContain('savings')
    expect(ids).not.toContain('biggest')
    expect(ids).not.toContain('onTrack')
    expect(ids).not.toContain('vsUsual') // not a single month
  })
  it('an empty period shows the empty card only', () => {
    const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, total: 0 } })
    expect(visibleWidgets(empty, { lens: 'household', period: THIS })).toEqual(['headline', 'empty'])
  })
})

describe('sentences', () => {
  it('says more, less or about the same', () => {
    expect(paidOutSentence(141.2, { me: true, name: 'Giorgos' }, 'this month')).toBe('You paid €141.20 more than your share this month')
    expect(paidOutSentence(-20, { me: false, name: 'Maria' }, 'last month')).toBe('Maria paid €20.00 less than their share last month')
    expect(paidOutSentence(0.6, { me: true, name: 'G' }, 'in this period')).toBe('You paid about the same as your share in this period')
  })
  it('writes the delta in words and signs', () => {
    expect(deltaText(-8)).toBe('−8% vs the previous period')
    expect(deltaText(12.5)).toBe('+12.5% vs the previous period')
    expect(deltaText(0)).toBe('Same as the previous period')
    expect(deltaText(null)).toBeNull()
  })
})
