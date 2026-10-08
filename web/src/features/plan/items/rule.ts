import type { RecurringItemOut } from '../../../data/types'
import { formatMonthName, formatShortDate, ordinal, parseISODate } from '../../../ui/format'

export const RULE_KINDS = ['monthly_day', 'last_business_day', 'yearly', 'easter_offset', 'weekly', 'monthly_interval'] as const
export type RuleKind = (typeof RULE_KINDS)[number]
export const RULE_ADJUSTS = ['none', 'previous_business_day', 'next_business_day'] as const
export type RuleAdjust = (typeof RULE_ADJUSTS)[number]

/** What the picker edits: one shape per schedule choice (spec §4.7). */
export type RuleChoice =
  | { kind: 'monthly_day'; day: number; adjust: RuleAdjust; everyMonths: number }
  | { kind: 'last_business_day'; everyMonths: number }
  | { kind: 'yearly'; day: number; month: number; adjust: RuleAdjust }
  | { kind: 'easter_offset'; days: number; adjust: RuleAdjust }
  | { kind: 'weekly'; weekday: number; everyWeeks: number }
  | { kind: 'monthly_interval'; everyMonths: number }

/** What the API stores (RecurringItemIn / RulePreviewIn). */
export interface RuleFields {
  rule_kind: RuleKind
  interval_months: number
  rule_day: number | null
  rule_month: number | null
  rule_adjust: RuleAdjust
  rule_days: number | null
  rule_weekday: number | null
  rule_interval_weeks: number | null
}

type StoredRule = Pick<RecurringItemOut,
  'rule_kind' | 'interval_months' | 'rule_day' | 'rule_month' | 'rule_adjust' | 'rule_days' | 'rule_weekday' | 'rule_interval_weeks'>

export const RULE_LABELS: Record<RuleKind, string> = {
  monthly_day: 'On a day of the month',
  last_business_day: 'Last business day of the month',
  yearly: 'Every year on a date',
  easter_offset: 'Easter ± days (Orthodox)',
  weekly: 'Every few weeks on a weekday',
  monthly_interval: 'Every few months from the start date',
}

export const ADJUST_LABELS: Record<RuleAdjust, string> = {
  none: 'Exact day',
  previous_business_day: 'Business day before',
  next_business_day: 'Business day after',
}

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const

const BLANK: RuleFields = {
  rule_kind: 'monthly_day', interval_months: 1, rule_day: null, rule_month: null, rule_adjust: 'none',
  rule_days: null, rule_weekday: null, rule_interval_weeks: null,
}

export function toRuleFields(c: RuleChoice): RuleFields {
  switch (c.kind) {
    case 'monthly_day':
      return { ...BLANK, rule_kind: c.kind, interval_months: c.everyMonths, rule_day: c.day, rule_adjust: c.adjust }
    case 'last_business_day':
      return { ...BLANK, rule_kind: c.kind, interval_months: c.everyMonths }
    case 'yearly':
      return { ...BLANK, rule_kind: c.kind, rule_day: c.day, rule_month: c.month, rule_adjust: c.adjust }
    case 'easter_offset':
      return { ...BLANK, rule_kind: c.kind, rule_days: c.days, rule_adjust: c.adjust }
    case 'weekly':
      return { ...BLANK, rule_kind: c.kind, rule_weekday: c.weekday, rule_interval_weeks: c.everyWeeks }
    case 'monthly_interval':
      return { ...BLANK, rule_kind: c.kind, interval_months: c.everyMonths }
  }
}

const asAdjust = (v: string): RuleAdjust => ((RULE_ADJUSTS as readonly string[]).includes(v) ? (v as RuleAdjust) : 'none')

/** A stored rule as a picker choice; missing numbers come from the start date. */
export function fromRuleFields(r: StoredRule, startDate: string): RuleChoice {
  const start = parseISODate(startDate)
  const every = r.interval_months > 0 ? r.interval_months : 1
  switch (r.rule_kind) {
    case 'monthly_day':
      return { kind: 'monthly_day', day: r.rule_day ?? start.getDate(), adjust: asAdjust(r.rule_adjust), everyMonths: every }
    case 'last_business_day':
      return { kind: 'last_business_day', everyMonths: every }
    case 'yearly':
      return { kind: 'yearly', day: r.rule_day ?? start.getDate(), month: r.rule_month ?? start.getMonth() + 1, adjust: asAdjust(r.rule_adjust) }
    case 'easter_offset':
      return { kind: 'easter_offset', days: r.rule_days ?? 0, adjust: asAdjust(r.rule_adjust) }
    case 'weekly':
      // JS: Sunday = 0; the API: Monday = 0.
      return { kind: 'weekly', weekday: r.rule_weekday ?? (start.getDay() + 6) % 7, everyWeeks: r.rule_interval_weeks ?? 1 }
    default:
      return { kind: 'monthly_interval', everyMonths: every }
  }
}

/** The choice the picker switches to when the user picks another kind. */
export function defaultChoice(kind: RuleKind, startDate: string): RuleChoice {
  return fromRuleFields({ ...BLANK, rule_kind: kind }, startDate)
}

const adjustText = (a: RuleAdjust) =>
  a === 'previous_business_day' ? ', or the business day before' : a === 'next_business_day' ? ', or the business day after' : ''
const everyText = (n: number) => (n > 1 ? ` · every ${n} months` : '')

/** Plain language: "26th, or the business day before", "Last business day". */
export function ruleSummary(c: RuleChoice, startDate: string): string {
  switch (c.kind) {
    case 'monthly_day':
      return `${ordinal(c.day)}${c.adjust === 'none' ? ' of the month' : adjustText(c.adjust)}${everyText(c.everyMonths)}`
    case 'last_business_day':
      return `Last business day${everyText(c.everyMonths)}`
    case 'yearly':
      return `Every year on ${c.day} ${formatMonthName(c.month)}${adjustText(c.adjust)}`
    case 'easter_offset': {
      const n = Math.abs(c.days)
      const base = c.days === 0 ? 'Easter Sunday' : `${n} day${n === 1 ? '' : 's'} ${c.days < 0 ? 'before' : 'after'} Easter`
      return base + adjustText(c.adjust)
    }
    case 'weekly':
      return c.everyWeeks === 1 ? `Every ${WEEKDAYS[c.weekday]}` : `Every ${c.everyWeeks} weeks on ${WEEKDAYS[c.weekday]}`
    case 'monthly_interval':
      return c.everyMonths === 1
        ? `Every month from ${formatShortDate(startDate)}`
        : `Every ${c.everyMonths} months from ${formatShortDate(startDate)}`
  }
}
