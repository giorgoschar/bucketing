import { describe, expect, it } from 'vitest'
import { makeInsights } from './fixtures'
import { deltaText, paidOutSentence, summaryParts, visibleWidgets } from './overview'

const THIS = { preset: 'this_month' } as const

const EMPTY = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, total: 0 } })
const NO_MIN = makeInsights({ fuel: null, kpis: { ...makeInsights().kpis, savings_rate: null, largest: null } })

// Phase C §2.2: the old single list is now three tabs; Summary stands for headline, On track, In/Out/Net and Savings rate.
describe('visibleWidgets', () => {
  it('Overview, household this month: Summary, Where it went, Categories vs usual, Budgets', () => {
    expect(visibleWidgets(makeInsights(), { lens: 'household', period: THIS })).toEqual(['summary', 'where', 'vsUsual', 'budgets'])
  })
  it('Overview, member lens: identity and share first, and no Categories vs usual', () => {
    expect(visibleWidgets(makeInsights(), { lens: 'm', period: THIS })).toEqual(['identity', 'share', 'summary', 'where', 'budgets'])
  })
  it('Trends: By month, Biggest expense, How you paid, Fuel', () => {
    expect(visibleWidgets(makeInsights(), { tab: 'trends', lens: 'household', period: THIS })).toEqual(['byMonth', 'biggest', 'method', 'fuel'])
    expect(visibleWidgets(makeInsights(), { tab: 'trends', lens: 'm', period: THIS })).toEqual(['byMonth', 'biggest', 'method', 'fuel'])
  })
  it('Trends on desktop adds the two tables', () => {
    expect(visibleWidgets(makeInsights(), { tab: 'trends', lens: 'household', period: THIS, desktop: true })).toEqual(
      ['byMonth', 'biggest', 'method', 'fuel', 'monthsTable', 'categoriesTable'],
    )
  })
  it('Bills & statements: Bills (the panel on desktop) then Statements', () => {
    const o = { tab: 'bills', lens: 'household', period: THIS, bills: true, statements: true } as const
    expect(visibleWidgets(makeInsights(), o)).toEqual(['bills', 'statements'])
    expect(visibleWidgets(makeInsights(), { ...o, desktop: true })).toEqual(['billsPanel', 'statements'])
  })
  it('the same lists in a past-month period, minus the household-only cards outside a single month', () => {
    const last3 = { preset: 'last_3m' } as const
    expect(visibleWidgets(makeInsights(), { lens: 'household', period: last3 })).toEqual(['summary', 'where', 'budgets'])
    expect(visibleWidgets(makeInsights(), { lens: 'household', period: { preset: 'last_month' } })).toEqual(['summary', 'where', 'vsUsual', 'budgets'])
  })
  it('hides cards on null data', () => {
    expect(visibleWidgets(NO_MIN, { tab: 'trends', lens: 'household', period: THIS })).toEqual(['byMonth', 'method'])
    const bare = makeInsights({ categories: [], budget_status: [] })
    expect(visibleWidgets(bare, { lens: 'household', period: THIS })).toEqual(['summary', 'vsUsual'])
    expect(visibleWidgets(bare, { tab: 'trends', lens: 'household', period: THIS, desktop: true })).not.toContain('categoriesTable')
  })
  it('an empty period: Overview shows the Summary (spent figure only) and the empty card; the other tabs work as usual', () => {
    expect(visibleWidgets(EMPTY, { lens: 'household', period: THIS })).toEqual(['summary', 'empty'])
    expect(visibleWidgets(EMPTY, { lens: 'm', period: THIS })).toEqual(['identity', 'share', 'summary', 'empty'])
    expect(visibleWidgets(EMPTY, { tab: 'trends', lens: 'household', period: THIS }).slice(0, 1)).toEqual(['byMonth'])
    expect(visibleWidgets(EMPTY, { tab: 'bills', lens: 'household', period: THIS, bills: true, statements: true })).toEqual(['bills', 'statements'])
  })
})

describe('summaryParts', () => {
  it('each line is where its old card was: On track = household this month, Savings = a rate exists', () => {
    expect(summaryParts(makeInsights(), { lens: 'household', period: THIS })).toEqual({ onTrack: true, inOut: true, savings: true })
    expect(summaryParts(makeInsights(), { lens: 'm', period: THIS })).toEqual({ onTrack: false, inOut: true, savings: true })
    expect(summaryParts(makeInsights(), { lens: 'household', period: { preset: 'last_month' } }).onTrack).toBe(false)
    expect(summaryParts(NO_MIN, { lens: 'household', period: THIS }).savings).toBe(false)
    expect(summaryParts(EMPTY, { lens: 'household', period: THIS })).toEqual({ onTrack: false, inOut: false, savings: false })
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
