import type { RecurringItemIn, RecurringItemOut } from '../../../data/types'
import { parseAmount } from '../../../ui/format'
import { defaultChoice, fromRuleFields, toRuleFields, type RuleChoice } from './rule'

export interface ItemForm {
  id: string | null
  name: string
  direction: 'in' | 'out'
  /** As typed; blank = variable. */
  amount: string
  currency: string
  rule: RuleChoice
  start_date: string
  /** '' = no end. */
  end_date: string
  bucket_id: string
  category_id: string
  paid_by_default: string
  is_auto_pay: boolean
  is_active: boolean
  notes: string
  /** Not edited in this sheet; carried through so a PUT (which replaces the row) never drops them. */
  keep: Required<Pick<RecurringItemIn, 'payer_mode' | 'splits'>> & Pick<RecurringItemIn, 'total_occurrences' | 'contract_end_date'>
}

export function emptyItemForm(today: string, me: string | null): ItemForm {
  return {
    id: null, name: '', direction: 'out', amount: '', currency: 'EUR', rule: defaultChoice('monthly_day', today),
    start_date: today, end_date: '', bucket_id: '', category_id: '', paid_by_default: me ?? '', is_auto_pay: false,
    is_active: true, notes: '', keep: { payer_mode: 'single', splits: [], total_occurrences: null, contract_end_date: null },
  }
}

export function itemToForm(item: RecurringItemOut): ItemForm {
  return {
    id: item.id,
    name: item.name,
    direction: item.direction === 'in' ? 'in' : 'out',
    amount: item.amount === null ? '' : item.amount.toFixed(2),
    currency: item.currency,
    rule: fromRuleFields(item, item.start_date),
    start_date: item.start_date,
    end_date: item.end_date ?? '',
    bucket_id: item.bucket_id ?? '',
    category_id: item.category_id ?? '',
    paid_by_default: item.paid_by_default ?? '',
    is_auto_pay: item.is_auto_pay,
    is_active: item.is_active,
    notes: item.notes ?? '',
    keep: {
      payer_mode: item.payer_mode,
      splits: item.splits.map((s) => ({ user_id: s.user_id, amount: s.amount })),
      total_occurrences: item.total_occurrences,
      contract_end_date: item.contract_end_date,
    },
  }
}

/** The first problem as a sentence, or null when the form can be saved. */
export function validateItemForm(f: ItemForm): string | null {
  if (!f.name.trim()) return 'Give the item a name.'
  if (f.name.trim().length > 100) return 'Keep the name under 100 characters.'
  if (parseAmount(f.amount) === undefined) return 'Enter the amount like 38.90, or leave it blank for a variable amount.'
  if (!/^[A-Za-z]{3}$/.test(f.currency.trim())) return 'Use a 3-letter currency code, like EUR.'
  if (!f.start_date) return 'Pick a start date.'
  if (f.end_date && f.end_date < f.start_date) return 'The end date is before the start date.'
  return null
}

type Share = { user_id: string; amount: number | string }

/**
 * Shares scaled to a new total, each rounded to cents, the rounding remainder on the first share,
 * so they sum to the amount exactly (the server's check_split_sum). Unchanged when already equal.
 */
export function scaleSplits(splits: Share[], amount: number): { user_id: string; amount: number }[] {
  const cents = splits.map((s) => Math.round(Number(s.amount) * 100))
  const oldTotal = cents.reduce((a, b) => a + b, 0)
  const newTotal = Math.round(amount * 100)
  if (splits.length === 0 || oldTotal === 0 || oldTotal === newTotal) {
    return splits.map((s) => ({ user_id: s.user_id, amount: Number(s.amount) }))
  }
  const scaled = cents.map((c) => Math.round((c * newTotal) / oldTotal))
  scaled[0] += newTotal - scaled.reduce((a, b) => a + b, 0)
  return splits.map((s, i) => ({ user_id: s.user_id, amount: scaled[i] / 100 }))
}

/** True when saving this form would change the shares (the amount no longer matches their sum). */
export function sharesNeedScaling(f: ItemForm): boolean {
  const amount = parseAmount(f.amount)
  if (f.direction !== 'out' || !amount || f.keep.splits.length === 0) return false
  const sum = f.keep.splits.reduce((a, s) => a + Math.round(Number(s.amount) * 100), 0)
  return sum !== Math.round(Number(amount) * 100)
}

/** The full RecurringItemIn (POST and PUT). Call validateItemForm first. */
export function formToBody(f: ItemForm): RecurringItemIn {
  const out = f.direction === 'out'
  return {
    name: f.name.trim(),
    direction: f.direction,
    amount: parseAmount(f.amount) ?? null,
    currency: f.currency.trim().toUpperCase(),
    ...toRuleFields(f.rule),
    start_date: f.start_date,
    end_date: f.end_date || null,
    bucket_id: out ? f.bucket_id || null : null,
    category_id: f.category_id || null,
    paid_by_default: f.keep.payer_mode === 'own_share' ? null : f.paid_by_default || null,
    is_auto_pay: out && f.is_auto_pay,
    is_active: f.is_active,
    notes: f.notes.trim() || null,
    payer_mode: out ? f.keep.payer_mode : 'single',
    splits: out ? scaleFormSplits(f) : [],
    total_occurrences: f.keep.total_occurrences ?? null,
    contract_end_date: f.keep.contract_end_date ?? null,
  }
}

function scaleFormSplits(f: ItemForm) {
  const amount = parseAmount(f.amount)
  return amount ? scaleSplits(f.keep.splits, Number(amount)) : f.keep.splits
}

/** The row Items shows while a create or edit waits in the queue. */
export function pendingItem(body: RecurringItemIn, id: string): RecurringItemOut {
  return {
    id,
    name: body.name,
    direction: body.direction ?? 'out',
    amount: body.amount == null ? null : Number(body.amount),
    currency: body.currency ?? 'EUR',
    category_id: body.category_id ?? null,
    bucket_id: body.bucket_id ?? null,
    rule_kind: body.rule_kind ?? 'monthly_day',
    interval_months: body.interval_months ?? 1,
    rule_day: body.rule_day ?? null,
    rule_month: body.rule_month ?? null,
    rule_adjust: body.rule_adjust ?? 'none',
    rule_days: body.rule_days ?? null,
    rule_weekday: body.rule_weekday ?? null,
    rule_interval_weeks: body.rule_interval_weeks ?? null,
    start_date: body.start_date,
    end_date: body.end_date ?? null,
    total_occurrences: body.total_occurrences ?? null,
    contract_end_date: body.contract_end_date ?? null,
    paid_by_default: body.paid_by_default ?? null,
    payer_mode: body.payer_mode ?? 'single',
    is_auto_pay: body.is_auto_pay ?? false,
    is_active: body.is_active ?? true,
    notes: body.notes ?? null,
    splits: (body.splits ?? []).map((s) => ({ user_id: s.user_id, amount: Number(s.amount) })),
    next_entry: null,
    has_history: false,
  }
}
