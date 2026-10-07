import { beforeEach, describe, expect, it } from 'vitest'
import { db, wipe } from '../../offline/db'
import {
  EMPTY_DEFAULTS, defaultsKey, fold, initialNew, learn, loadDefaults, matchRule, sanitize, saveDefaults,
  shouldOfferRemember, suggestMerchants, type DefaultsRecord,
} from './defaults'
import { blankState, type ComposerState } from './state'
import type { Bucket, Category } from './types'

const bucket = (id: string, over: Partial<Bucket> = {}): Bucket => ({
  id, name: id, kind: 'monthly', status: 'active', budget: null, start_date: null, end_date: null, show_income: false, ...over,
})
const category = (id: string, over: Partial<Category> = {}): Category => ({
  id, name: id, icon: null, color: null, system_key: null, ...over,
})
const BUCKETS = [bucket('b-day'), bucket('b-old', { status: 'archived' }), bucket('b-salary', { show_income: true })]
const CATEGORIES = [category('c-coffee'), category('c-fuel', { system_key: 'fuel' })]
const ctx = (defaults: DefaultsRecord, type: 'expense' | 'income' = 'expense', cash = false) => ({
  defaults, buckets: BUCKETS, categories: CATEGORIES, memberIds: ['u1', 'u2'], meId: 'u1',
  householdCurrency: 'EUR', type, today: '2026-10-07', clientId: 'c1', cash,
})

beforeEach(() => wipe())

describe('initial defaults', () => {
  it('first use: no budget (dashed), payer me, method card, household currency, today', () => {
    expect(initialNew(ctx(EMPTY_DEFAULTS))).toMatchObject({
      bucketId: null, categoryId: null, paidBy: 'u1', method: 'card', currency: 'EUR', rate: '1', date: '2026-10-07', clientId: 'c1',
    })
  })
  it('uses the last entry, dropping an archived budget, a missing category and a former member', () => {
    const d = { ...EMPTY_DEFAULTS, last: { bucket_id: 'b-old', category_id: 'c-gone', paid_by: 'u9', payment_method: 'apple_pay' as const } }
    expect(initialNew(ctx(d))).toMatchObject({ bucketId: null, categoryId: null, paidBy: 'u1', method: 'apple_pay' })
    const ok = { ...EMPTY_DEFAULTS, last: { bucket_id: 'b-day', category_id: 'c-coffee', paid_by: 'u2', payment_method: 'cash' as const } }
    expect(initialNew(ctx(ok))).toMatchObject({ bucketId: 'b-day', categoryId: 'c-coffee', paidBy: 'u2', method: 'cash' })
  })
  it('income uses lastIncome, only show_income budgets, and transfer', () => {
    const d = { ...EMPTY_DEFAULTS, lastIncome: { bucket_id: 'b-day', category_id: null, paid_by: 'u2' } }
    expect(initialNew(ctx(d, 'income'))).toMatchObject({ type: 'income', bucketId: null, paidBy: 'u2', method: 'transfer' })
    expect(sanitize({ bucket_id: 'b-salary' }, { buckets: BUCKETS, categories: CATEGORIES, memberIds: ['u1'], type: 'income' })).toEqual({ bucket_id: 'b-salary' })
  })
  it('cash mode from the start', () => {
    expect(initialNew(ctx(EMPTY_DEFAULTS, 'expense', true))).toMatchObject({ cashMode: true, method: 'cash', tookFrom: 'stash', paidBy: 'u1' })
  })
})

describe('learning', () => {
  const s = (over: Partial<ComposerState>): ComposerState => ({
    ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'c1', meId: 'u1' }), ...over,
  })
  it('remembers last, per category, per budget, recent categories (max 4), rate and fuel price', () => {
    let rec = { ...EMPTY_DEFAULTS, recentCategoryIds: ['a', 'b', 'c', 'd'] }
    rec = learn(rec, s({ bucketId: 'b-car', categoryId: 'c-fuel', paidBy: 'u2', method: 'card', currency: 'GBP', rate: '1.15', fuelPrice: '1.789' }), { householdCurrency: 'EUR', fuelCategoryId: 'c-fuel' })
    expect(rec.last).toEqual({ bucket_id: 'b-car', category_id: 'c-fuel', paid_by: 'u2', payment_method: 'card' })
    expect(rec.byCategory['c-fuel']).toEqual({ bucket_id: 'b-car', paid_by: 'u2', payment_method: 'card' })
    expect(rec.byBucket['b-car']).toEqual({ category_id: 'c-fuel', paid_by: 'u2', payment_method: 'card' })
    expect(rec.recentCategoryIds).toEqual(['c-fuel', 'a', 'b', 'c'])
    expect(rec.rates).toEqual({ GBP: '1.15' })
    expect(rec.fuelPrice).toBe('1.789')
  })
  it('own share keeps the previous payer; income writes only lastIncome; edits teach nothing', () => {
    const rec = { ...EMPTY_DEFAULTS, last: { paid_by: 'u2' } }
    expect(learn(rec, s({ ownShare: true, paidBy: null, bucketId: 'b-day' }), { householdCurrency: 'EUR', fuelCategoryId: null }).last?.paid_by).toBe('u2')
    const inc = learn(EMPTY_DEFAULTS, s({ type: 'income', bucketId: null, paidBy: 'u2', method: 'transfer' }), { householdCurrency: 'EUR', fuelCategoryId: null })
    expect(inc.last).toBeUndefined()
    expect(inc.lastIncome).toEqual({ bucket_id: null, category_id: null, paid_by: 'u2', payment_method: 'transfer' })
    expect(learn(rec, s({ mode: 'edit', bucketId: 'b-x' }), { householdCurrency: 'EUR', fuelCategoryId: null })).toBe(rec)
  })
  it('round-trips through the encrypted cache; an unreadable record gives empty defaults', async () => {
    await saveDefaults('h1', { ...EMPTY_DEFAULTS, fuelPrice: '1.7' })
    expect((await loadDefaults('h1')).fuelPrice).toBe('1.7')
    await db.cache.put({ key: defaultsKey('h2'), iv: new Uint8Array(12), data: new ArrayBuffer(8), updatedAt: 0 })
    expect(await loadDefaults('h2')).toEqual(EMPTY_DEFAULTS)
  })
})

describe('rules', () => {
  it('fold: case, accents, final sigma, spaces (mirrors the server)', () => {
    expect(fold('ΣΚΛΑΒΕΝΙΤΗΣ')).toBe('σκλαβενιτησ')
    expect(fold('  Καφέ   Ιsland ')).toBe('καφε ιsland')
    expect(fold(null)).toBe('')
  })
  it('matches a substring, the longest pattern wins', () => {
    const rules = [
      { id: 'r1', pattern: 'island', category_id: 'c-travel' },
      { id: 'r2', pattern: 'coffee island', category_id: 'c-coffee' },
      { id: 'r3', pattern: 'σκλαβενιτης', category_id: 'c-food' },
    ]
    expect(matchRule('COFFEE ISLAND Kifisia', rules)?.id).toBe('r2')
    expect(matchRule('Σκλαβενίτης', rules)?.id).toBe('r3')
    expect(matchRule('c', rules)).toBeNull()
  })
  it('suggests up to 5 recent merchants after 2 characters', () => {
    const merchants = ['Coffee Island', 'Coffeeway', 'Lidl', 'Cosmote', 'Coffee Lab', 'Cofix', 'Coffee Berry']
    expect(suggestMerchants('c', merchants)).toEqual([])
    expect(suggestMerchants('cof', merchants)).toEqual(['Coffee Island', 'Coffeeway', 'Coffee Lab', 'Cofix', 'Coffee Berry'])
    expect(suggestMerchants('Lidl', merchants)).toEqual([])
  })
  it('offers Remember only for a QR review whose category differs from the server suggestion', () => {
    const qr = { ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'c', meId: 'u1' }), source: 'qr' as const, merchant: 'Taverna', categoryId: 'c-eat', scanCategoryId: 'c-food' }
    expect(shouldOfferRemember(qr, true)).toBe(true)
    expect(shouldOfferRemember(qr, false)).toBe(false)
    expect(shouldOfferRemember({ ...qr, categoryId: 'c-food' }, true)).toBe(false)
    expect(shouldOfferRemember({ ...qr, merchant: 'T' }, true)).toBe(false)
    expect(shouldOfferRemember({ ...qr, source: 'manual' }, true)).toBe(false)
  })
})
