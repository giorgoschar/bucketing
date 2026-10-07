import { describe, expect, it } from 'vitest'
import { item } from '../../../test/fixtures'
import { defaultChoice, fromRuleFields, ruleSummary, toRuleFields, type RuleChoice, type RuleFields } from './rule'

const none: Omit<RuleFields, 'rule_kind'> = {
  interval_months: 1, rule_day: null, rule_month: null, rule_adjust: 'none', rule_days: null, rule_weekday: null, rule_interval_weeks: null,
}

const cases: [RuleChoice, RuleFields][] = [
  [{ kind: 'monthly_day', day: 26, adjust: 'previous_business_day', everyMonths: 1 },
    { ...none, rule_kind: 'monthly_day', rule_day: 26, rule_adjust: 'previous_business_day' }],
  [{ kind: 'last_business_day', everyMonths: 1 }, { ...none, rule_kind: 'last_business_day' }],
  [{ kind: 'yearly', day: 21, month: 12, adjust: 'previous_business_day' },
    { ...none, rule_kind: 'yearly', rule_day: 21, rule_month: 12, rule_adjust: 'previous_business_day' }],
  [{ kind: 'easter_offset', days: -4, adjust: 'none' }, { ...none, rule_kind: 'easter_offset', rule_days: -4 }],
  [{ kind: 'weekly', weekday: 4, everyWeeks: 2 }, { ...none, rule_kind: 'weekly', rule_weekday: 4, rule_interval_weeks: 2 }],
  [{ kind: 'monthly_interval', everyMonths: 3 }, { ...none, rule_kind: 'monthly_interval', interval_months: 3 }],
]

describe('toRuleFields / fromRuleFields', () => {
  it.each(cases)('%o maps to its rule_* fields and back', (choice, fields) => {
    expect(toRuleFields(choice)).toEqual(fields)
    expect(fromRuleFields(fields, '2026-10-01')).toEqual(choice)
  })

  it('keeps an item’s interval on the monthly kinds', () => {
    const c = fromRuleFields({ ...none, rule_kind: 'monthly_day', rule_day: 5, interval_months: 2 }, '2026-01-05')
    expect(toRuleFields(c).interval_months).toBe(2)
  })

  it('unknown or legacy kinds read as "every N months from the start date"', () => {
    expect(fromRuleFields({ ...none, rule_kind: 'something_old', interval_months: 1 }, '2026-01-09'))
      .toEqual({ kind: 'monthly_interval', everyMonths: 1 })
  })

  it('a fresh choice takes its numbers from the start date', () => {
    expect(defaultChoice('monthly_day', '2026-10-07')).toEqual({ kind: 'monthly_day', day: 7, adjust: 'none', everyMonths: 1 })
    expect(defaultChoice('yearly', '2026-10-07')).toEqual({ kind: 'yearly', day: 7, month: 10, adjust: 'none' })
    expect(defaultChoice('weekly', '2026-10-07')).toEqual({ kind: 'weekly', weekday: 2, everyWeeks: 1 }) // a Wednesday
    expect(defaultChoice('easter_offset', '2026-10-07')).toEqual({ kind: 'easter_offset', days: 0, adjust: 'none' })
  })
})

describe('ruleSummary', () => {
  it('reads like the spec', () => {
    const s = (c: RuleChoice, start = '2026-12-03') => ruleSummary(c, start)
    expect(s({ kind: 'monthly_day', day: 26, adjust: 'previous_business_day', everyMonths: 1 })).toBe('26th, or the business day before')
    expect(s({ kind: 'monthly_day', day: 1, adjust: 'none', everyMonths: 1 })).toBe('1st of the month')
    expect(s({ kind: 'monthly_day', day: 15, adjust: 'next_business_day', everyMonths: 2 }))
      .toBe('15th, or the business day after · every 2 months')
    expect(s({ kind: 'last_business_day', everyMonths: 1 })).toBe('Last business day')
    expect(s({ kind: 'yearly', day: 21, month: 12, adjust: 'previous_business_day' }))
      .toBe('Every year on 21 December, or the business day before')
    expect(s({ kind: 'easter_offset', days: -4, adjust: 'none' })).toBe('4 days before Easter')
    expect(s({ kind: 'easter_offset', days: 1, adjust: 'none' })).toBe('1 day after Easter')
    expect(s({ kind: 'easter_offset', days: 0, adjust: 'none' })).toBe('Easter Sunday')
    expect(s({ kind: 'weekly', weekday: 0, everyWeeks: 1 })).toBe('Every Monday')
    expect(s({ kind: 'weekly', weekday: 4, everyWeeks: 2 })).toBe('Every 2 weeks on Friday')
    expect(s({ kind: 'monthly_interval', everyMonths: 3 })).toBe('Every 3 months from 3 Dec')
    expect(s({ kind: 'monthly_interval', everyMonths: 1 })).toBe('Every month from 3 Dec')
  })

  it('works on stored items', () => {
    const cosmote = item()
    expect(ruleSummary(fromRuleFields(cosmote, cosmote.start_date), cosmote.start_date)).toBe('9th of the month')
  })
})
