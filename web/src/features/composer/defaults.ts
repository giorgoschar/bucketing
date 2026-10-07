import type { paths } from '../../api/schema'
import { cacheGet, cachePut } from '../../offline/db'
import { parseFuelPrice, parseRate } from './amount'
import { blankState, type ComposerState, METHODS, type Remembered, reduce, type TxnType } from './state'
import type { Bucket, Category, Rule } from './types'

/**
 * 2d owns /api/v1/settings/category-rules (2d spec §7.4). The Remember toggle and rule matching need
 * that path in the generated types. 2d-B has landed, so this is `true`; setting it back to `false` fails
 * the type check ('false' is not assignable to 'true'), and so would removing the path from the API.
 */
type HasRulesApi = '/api/v1/settings/category-rules' extends keyof paths ? true : false
export const RULES_API_READY: HasRulesApi = true

export interface DefaultsRecord {
  v: 1
  last?: Remembered
  lastIncome?: Remembered
  byCategory: Record<string, Remembered>
  byBucket: Record<string, Remembered>
  recentCategoryIds: string[]
  /** Last rate typed per currency code. */
  rates: Record<string, string>
  fuelPrice?: string
}

export const EMPTY_DEFAULTS: DefaultsRecord = { v: 1, byCategory: {}, byBucket: {}, recentCategoryIds: [], rates: {} }

/** Plaintext key (db.ts NOTE): no sensitive values in it, only the household id. */
export const defaultsKey = (hh: string) => `composer.defaults:${hh}`

export async function loadDefaults(hh: string): Promise<DefaultsRecord> {
  try {
    const r = await cacheGet<DefaultsRecord>(defaultsKey(hh))
    return r && r.v === 1 ? { ...EMPTY_DEFAULTS, ...r } : EMPTY_DEFAULTS
  } catch {
    return EMPTY_DEFAULTS // unreadable or wiped: start empty, never fail (spec §8)
  }
}

export async function saveDefaults(hh: string, rec: DefaultsRecord): Promise<void> {
  try {
    await cachePut(defaultsKey(hh), rec)
  } catch {
    // A wipe mid-write: the next save writes again.
  }
}

export interface LookupCtx { buckets: Bucket[]; categories: Category[]; memberIds: string[]; type: TxnType }

/** Keep only what still exists: an active (for income, income-tracking) budget, a category, a member. */
export function sanitize(r: Remembered | undefined, ctx: LookupCtx): Remembered {
  if (!r) return {}
  const out: Remembered = {}
  const b = r.bucket_id ? ctx.buckets.find((x) => x.id === r.bucket_id) : undefined
  if (b && b.status === 'active' && (ctx.type === 'expense' || b.show_income)) out.bucket_id = b.id
  if (r.category_id && ctx.categories.some((c) => c.id === r.category_id)) out.category_id = r.category_id
  if (r.paid_by && ctx.memberIds.includes(r.paid_by)) out.paid_by = r.paid_by
  if (r.payment_method && METHODS.includes(r.payment_method)) out.payment_method = r.payment_method
  return out
}

export interface NewCtx {
  defaults: DefaultsRecord
  buckets: Bucket[]
  categories: Category[]
  memberIds: string[]
  meId: string
  householdCurrency: string
  type: TxnType
  today: string
  clientId: string
  cash: boolean
}

export function initialNew(c: NewCtx): ComposerState {
  const lookup = { buckets: c.buckets, categories: c.categories, memberIds: c.memberIds, type: c.type }
  const rem = sanitize(c.type === 'income' ? c.defaults.lastIncome : c.defaults.last, lookup)
  const s: ComposerState = {
    ...blankState({ type: c.type, currency: c.householdCurrency, date: c.today, clientId: c.clientId, meId: c.meId }),
    bucketId: rem.bucket_id ?? null,
    categoryId: rem.category_id ?? null,
    paidBy: rem.paid_by ?? c.meId,
    method: rem.payment_method ?? (c.type === 'income' ? 'transfer' : 'card'),
  }
  return c.cash && c.type === 'expense'
    ? reduce(s, { type: 'setCashMode', on: true, meId: c.meId, defaultMethod: s.method })
    : s
}

export interface LearnCtx { householdCurrency: string; fuelCategoryId: string | null }

/** Rewritten when Save is tapped, online or queued (spec §4.3). Edits of old entries teach nothing. */
export function learn(rec: DefaultsRecord, s: ComposerState, ctx: LearnCtx): DefaultsRecord {
  if (s.mode !== 'new') return rec
  const rates = s.currency !== ctx.householdCurrency && parseRate(s.rate) !== null ? { ...rec.rates, [s.currency]: s.rate.trim() } : rec.rates
  if (s.type === 'income') {
    return { ...rec, rates, lastIncome: { bucket_id: s.bucketId, category_id: s.categoryId, paid_by: s.paidBy, payment_method: s.method } }
  }
  const who: Remembered = s.ownShare ? {} : { paid_by: s.paidBy }
  const how: Remembered = { ...who, payment_method: s.method }
  const isFuel = ctx.fuelCategoryId !== null && s.categoryId === ctx.fuelCategoryId
  return {
    ...rec,
    rates,
    last: { ...rec.last, bucket_id: s.bucketId, category_id: s.categoryId, ...how },
    byCategory: s.categoryId ? { ...rec.byCategory, [s.categoryId]: { bucket_id: s.bucketId, ...how } } : rec.byCategory,
    byBucket: s.bucketId ? { ...rec.byBucket, [s.bucketId]: { category_id: s.categoryId, ...how } } : rec.byBucket,
    recentCategoryIds: s.categoryId
      ? [s.categoryId, ...rec.recentCategoryIds.filter((id) => id !== s.categoryId)].slice(0, 4)
      : rec.recentCategoryIds,
    fuelPrice: isFuel && parseFuelPrice(s.fuelPrice) !== null ? s.fuelPrice.trim() : rec.fuelPrice,
  }
}

/** Mirrors app/services/category_rules.fold: case-fold, strip accents, final ς → σ, collapse spaces. */
export function fold(text: string | null | undefined): string {
  if (!text) return ''
  const stripped = text.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
  return stripped.replace(/ς/g, 'σ').split(/\s+/).filter(Boolean).join(' ')
}

/** The household rule whose folded pattern is inside the folded merchant; the longest pattern wins. */
export function matchRule(merchant: string, rules: Rule[]): Rule | null {
  const m = fold(merchant)
  if (m.length < 2) return null
  let best: Rule | null = null
  let bestLen = 0
  for (const r of rules) {
    const p = fold(r.pattern)
    if (p.length >= 2 && m.includes(p) && p.length > bestLen) {
      best = r
      bestLen = p.length
    }
  }
  return best
}

export function suggestMerchants(query: string, merchants: string[]): string[] {
  const q = fold(query)
  if (q.length < 2) return []
  return merchants.filter((m) => fold(m).includes(q) && fold(m) !== q).slice(0, 5)
}

export function shouldOfferRemember(s: ComposerState, ready: boolean): boolean {
  return ready && s.source === 'qr' && fold(s.merchant).length >= 2 && s.categoryId !== null && s.categoryId !== s.scanCategoryId
}

export const fuelCategoryId = (categories: Category[]): string | null =>
  categories.find((c) => c.system_key === 'fuel')?.id ?? null
