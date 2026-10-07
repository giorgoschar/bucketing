import type { components } from '../../api/schema'
import { centsToString, convertCents, fromApiAmount, parseFuelPrice, parseRate, toCents } from './amount'
import { formatCents } from './currencies'
import { typedFromShares } from './splits'
import { blankState, type ComposerState, type Method, METHODS } from './state'
import type { Txn } from './types'

export type CreateBody = components['schemas']['TransactionCreate']
export type UpdateBody = components['schemas']['TransactionUpdate']
export interface ModelCtx { householdCurrency: string; fuelCategoryId: string | null }

const decimal = (s: string) => s.trim().replace(',', '.')

export const isFuel = (s: ComposerState, ctx: ModelCtx): boolean =>
  s.type === 'expense' && ctx.fuelCategoryId !== null && s.categoryId === ctx.fuelCategoryId

const tookCash = (s: ComposerState) => s.type === 'expense' && s.method === 'cash' && s.tookFrom !== 'none' && !s.ownShare

export function toCreateBody(s: ComposerState, ctx: ModelCtx): CreateBody {
  const body: CreateBody = {
    type: s.type,
    amount: centsToString(toCents(s.amount)),
    currency: s.currency,
    exchange_rate: s.currency === ctx.householdCurrency ? '1' : decimal(s.rate),
    bucket_id: s.fixedCost ? null : s.bucketId,
    category_id: s.categoryId,
    merchant: s.merchant.trim() || null,
    paid_by: s.ownShare ? null : s.paidBy,
    payer_mode: s.ownShare ? 'own_share' : 'single',
    payment_method: s.method,
    took_cash: tookCash(s),
    transaction_date: s.date,
    notes: s.notes.trim() || null,
    splits: s.type === 'expense' && (s.ownShare || s.splitOn) ? s.splits.map((x) => ({ user_id: x.user_id, amount: x.amount })) : [],
    exclude_from_forecast: !s.countInForecast,
    exclude_from_settlement: false,
    client_id: s.clientId,
  }
  if (body.took_cash) body.take_from = s.tookFrom
  if (isFuel(s, ctx) && s.fuelPrice.trim() !== '') body.fuel_price_per_litre = decimal(s.fuelPrice)
  return body
}

/** Full replacement (spec §4.10): no client_id or take, stored settlement flag, fuel price explicit. */
export function toUpdateBody(s: ComposerState, ctx: ModelCtx): UpdateBody {
  const { client_id: _client, take_from: _take, fuel_price_per_litre: _fuel, ...rest } = toCreateBody(s, ctx)
  return {
    ...rest,
    took_cash: false,
    exclude_from_settlement: s.excludeFromSettlement,
    fuel_price_per_litre: isFuel(s, ctx) && s.fuelPrice.trim() !== '' ? decimal(s.fuelPrice) : null,
  }
}

const asMethod = (m: string | null): Method => (METHODS as readonly string[]).includes(m ?? '') ? (m as Method) : 'card'

export function fromTransaction(t: Txn, c: { householdCurrency: string; meId: string }): ComposerState {
  const ownShare = t.payer_mode === 'own_share'
  const splits = t.splits.map((x) => ({ user_id: x.user_id, amount: centsToString(Math.round(Number(x.amount) * 100)) }))
  return {
    ...blankState({ type: t.type === 'income' ? 'income' : 'expense', currency: t.currency, date: t.transaction_date ?? '', clientId: null, meId: c.meId }),
    mode: 'edit',
    editId: t.id,
    amount: fromApiAmount(t.amount),
    rate: t.currency === c.householdCurrency ? '1' : String(t.exchange_rate),
    merchant: t.merchant ?? '',
    bucketId: t.bucket_id,
    fixedCost: t.type === 'expense' && t.bucket_id === null && t.recurring_bill_id !== null,
    categoryId: t.category_id,
    paidBy: ownShare ? null : t.paid_by,
    ownShare,
    method: asMethod(t.payment_method),
    notes: t.notes ?? '',
    fuelPrice: t.fuel_price_per_litre == null ? '' : String(t.fuel_price_per_litre),
    splitOn: !ownShare && splits.length > 0,
    splitMode: 'amounts',
    splits,
    splitTyped: typedFromShares(splits),
    countInForecast: !t.exclude_from_forecast,
    excludeFromSettlement: t.exclude_from_settlement,
    storedReceiptPath: t.receipt_path,
    touched: ['bucket', 'category', 'payer', 'method'],
  }
}

/** /new?from=<id>: the old "Duplicate" action. */
export function copyOf(s: ComposerState, c: { clientId: string; today: string }): ComposerState {
  return {
    ...s, mode: 'new', editId: null, clientId: c.clientId, date: c.today, storedReceiptPath: null, receipt: null,
    excludeFromSettlement: false, fixedCost: false, bucketId: s.fixedCost ? null : s.bucketId,
  }
}

/** The amount in household cents, or null when a foreign rate is missing. */
export function homeCents(s: ComposerState, householdCurrency: string): number | null {
  const cents = toCents(s.amount)
  if (s.currency === householdCurrency) return cents
  const rate = parseRate(s.rate)
  return rate === null ? null : convertCents(cents, rate)
}

export type Problem = 'amount' | 'bucket' | 'date' | 'rate' | 'fuel' | 'split' | 'wallet' | 'payer'
export interface ValidateCtx extends ModelCtx { today: string; stashCents: number | null; meId: string }
export interface Validation { ok: boolean; problems: Partial<Record<Problem, string>> }

export function validate(s: ComposerState, c: ValidateCtx): Validation {
  const p: Partial<Record<Problem, string>> = {}
  const cents = toCents(s.amount)
  if (cents <= 0) p.amount = 'Enter an amount'
  if (s.type === 'expense' && !s.bucketId && !s.fixedCost) p.bucket = 'Choose a budget'
  if (s.date > c.today) p.date = "Date can't be in the future"
  if (s.currency !== c.householdCurrency && parseRate(s.rate) === null) p.rate = 'Enter the rate'
  if (isFuel(s, c) && s.fuelPrice.trim() !== '' && parseFuelPrice(s.fuelPrice) === null) {
    p.fuel = /[.,]\d{4,}$/.test(s.fuelPrice.trim()) ? 'Use at most 3 decimals' : 'Price must be above 0'
  }
  if (s.type === 'expense' && (s.splitOn || s.ownShare)) {
    const sum = s.splits.reduce((a, x) => a + toCents(x.amount), 0)
    const negative = s.splits.some((x) => x.amount.trim().startsWith('-'))
    if (s.ownShare && Math.abs(sum - cents) > 1) p.split = `Who paid what must add up to ${formatCents(cents, s.currency)}`
    else if (negative || sum > cents) p.split = 'Fix the split'
  }
  if (tookCash(s) && s.paidBy !== c.meId) p.payer = 'Cash taken must be paid by you'
  if (tookCash(s) && s.tookFrom === 'stash' && c.stashCents !== null) {
    const home = homeCents(s, c.householdCurrency)
    if (home !== null && home > c.stashCents) p.wallet = `Your wallet has ${formatCents(c.stashCents, c.householdCurrency)}`
  }
  return { ok: Object.keys(p).length === 0, problems: p }
}

const HINT_ORDER: Problem[] = ['bucket', 'rate', 'date', 'split', 'wallet', 'payer', 'fuel']

/** The reason shown above the keypad when Save is disabled (an empty amount needs no words). */
export const firstProblem = (p: Validation['problems']): string | null =>
  HINT_ORDER.map((k) => p[k]).find((x) => x !== undefined) ?? null

export const isDirtyNew = (s: ComposerState): boolean =>
  toCents(s.amount) > 0 || s.notes.trim() !== '' || s.merchant.trim() !== ''

export function moreDirty(s: ComposerState, c: ModelCtx & { today: string }): boolean {
  return (
    s.date !== c.today ||
    s.notes.trim() !== '' ||
    (isFuel(s, c) && s.fuelPrice.trim() !== '') ||
    s.currency !== c.householdCurrency ||
    s.splitOn ||
    !s.countInForecast ||
    s.receipt !== null ||
    s.storedReceiptPath !== null
  )
}
