import { describe, expect, it } from 'vitest'
import { blankState, reduce, type ComposerState } from './state'

const base = (over: Partial<ComposerState> = {}): ComposerState => ({
  ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'c1', meId: 'u1' }),
  bucketId: 'b-day', categoryId: 'c-coffee', paidBy: 'u1', method: 'card',
  ...over,
})

describe('re-defaulting respects touched', () => {
  it('picking a category fills budget, payer and method that were not picked by hand', () => {
    const s = reduce(base({ touched: ['payer'] }), {
      type: 'pickCategory', id: 'c-fuel', remembered: { bucket_id: 'b-car', paid_by: 'u2', payment_method: 'cash' },
    })
    expect(s).toMatchObject({ categoryId: 'c-fuel', bucketId: 'b-car', paidBy: 'u1', method: 'cash' })
    expect(s.touched).toEqual(['payer', 'category'])
  })
  it('picking a budget fills category, payer and method; a hand-picked category stays', () => {
    const s = reduce(base({ touched: ['category'] }), {
      type: 'pickBucket', id: 'b-car', remembered: { category_id: 'c-fuel', paid_by: 'u2', payment_method: 'apple_pay' },
    })
    expect(s).toMatchObject({ bucketId: 'b-car', categoryId: 'c-coffee', paidBy: 'u2', method: 'apple_pay' })
  })
  it('a merchant rule sets an untouched category and labels it; a touched one stays', () => {
    const rule = { pattern: 'coffee island', category_id: 'c-coffee2' }
    expect(reduce(base(), { type: 'setMerchant', value: 'Coffee Island', rule })).toMatchObject({
      categoryId: 'c-coffee2', ruleLabel: 'rule: coffee island',
    })
    expect(reduce(base({ touched: ['category'] }), { type: 'setMerchant', value: 'Coffee Island', rule }).categoryId).toBe('c-coffee')
  })
  it('a filled method that is not cash clears "Took from"', () => {
    const s = reduce(base({ method: 'cash', tookFrom: 'bank' }), { type: 'pickCategory', id: 'c-x', remembered: { payment_method: 'card' } })
    expect(s).toMatchObject({ method: 'card', tookFrom: 'none' })
  })
})

describe('modes and fields', () => {
  it('cash from wallet sets cash, my wallet and locks the payer to me; off restores the method', () => {
    const on = reduce(base({ paidBy: 'u2' }), { type: 'setCashMode', on: true, meId: 'u1', defaultMethod: 'apple_pay' })
    expect(on).toMatchObject({ cashMode: true, method: 'cash', tookFrom: 'stash', paidBy: 'u1', ownShare: false })
    expect(reduce(on, { type: 'setCashMode', on: false, meId: 'u1', defaultMethod: 'apple_pay' })).toMatchObject({
      cashMode: false, method: 'apple_pay', tookFrom: 'none',
    })
  })
  it('switching to income resets the pills from the income defaults; edit cannot switch', () => {
    const s = reduce(base({ splitOn: true, splits: [{ user_id: 'u1', amount: '1.00' }], touched: ['bucket'] }), {
      type: 'setType', value: 'income', defaults: { paid_by: 'u2' },
    })
    expect(s).toMatchObject({ type: 'income', bucketId: null, categoryId: null, paidBy: 'u2', method: 'transfer', splitOn: false, splits: [], touched: [] })
    expect(reduce(base({ mode: 'edit' }), { type: 'setType', value: 'income', defaults: {} }).type).toBe('expense')
  })
  it('own share drops the single payer and any took-from', () => {
    const shares = [{ user_id: 'u1', amount: '5.00' }, { user_id: 'u2', amount: '5.00' }]
    expect(reduce(base({ method: 'cash', tookFrom: 'stash' }), { type: 'setOwnShare', splits: shares })).toMatchObject({
      ownShare: true, paidBy: null, tookFrom: 'none', splits: shares,
    })
  })
  it('picking a currency uses the last rate, or "1" for the household currency', () => {
    expect(reduce(base(), { type: 'pickCurrency', code: 'GBP', householdCurrency: 'EUR', lastRate: '1.15' }).rate).toBe('1.15')
    expect(reduce(base(), { type: 'pickCurrency', code: 'USD', householdCurrency: 'EUR', lastRate: undefined }).rate).toBe('')
    expect(reduce(base({ currency: 'GBP', rate: '1.15' }), { type: 'pickCurrency', code: 'EUR', householdCurrency: 'EUR', lastRate: undefined }).rate).toBe('1')
  })
  it('caps notes at 500 and merchant at 100', () => {
    expect(reduce(base(), { type: 'setNotes', value: 'x'.repeat(600) }).notes).toHaveLength(500)
    expect(reduce(base(), { type: 'setMerchant', value: 'y'.repeat(150), rule: null }).merchant).toHaveLength(100)
  })
})

describe('scan', () => {
  const result = { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' }
  it('fills the receipt fields and tags them until edited', () => {
    const s = reduce(base(), { type: 'applyScan', result, householdCurrency: 'EUR', today: '2026-10-07' })
    expect(s).toMatchObject({ amount: '12.50', merchant: 'Test Taverna', categoryId: 'c-eat', date: '2026-10-05', source: 'qr', scanCategoryId: 'c-eat', rememberRule: true })
    expect(s.fromReceipt).toEqual(['amount', 'currency', 'date', 'merchant', 'category'])
    expect(reduce(s, { type: 'key', key: '0' }).fromReceipt).not.toContain('amount')
  })
  it('no total: amount stays empty and the hint flag is set; a future date is ignored', () => {
    const s = reduce(base(), { type: 'applyScan', result: { ...result, amount: null, date: '2026-12-01' }, householdCurrency: 'EUR', today: '2026-10-07' })
    expect(s).toMatchObject({ amount: '', scanNoTotal: true, date: '2026-10-07' })
  })
})

describe('splits follow the amount (I1)', () => {
  const type = (s: ComposerState, keys: string) => [...keys].reduce((x, k) => reduce(x, { type: 'key', key: k as never }), s)
  const two = (u1: string, u2: string) => [{ user_id: 'u1', amount: u1 }, { user_id: 'u2', amount: u2 }]

  it('equal: re-equalises, leftover cent to the payer', () => {
    const s = type(base({ amount: '10', splitOn: true, splitMode: 'equal', splits: two('5.00', '5.00'), paidBy: 'u2' }), '.01')
    expect(s.amount).toBe('10.01')
    expect(s.splits).toEqual(two('5.00', '5.01'))
  })
  it('amounts: typed shares stay, the payer takes the new remainder', () => {
    const s = reduce(
      base({ amount: '10', splitOn: true, splitMode: 'amounts', splits: two('6.50', '3.50'), splitTyped: { u2: '3.50' } }),
      { type: 'key', key: '0' },
    )
    expect(s.splits).toEqual(two('96.50', '3.50'))
  })
  it('percent: percents stay, shares recompute', () => {
    const s = reduce(
      base({ amount: '10', splitOn: true, splitMode: 'percent', splits: two('7.50', '2.50'), splitTyped: { u2: '25' } }),
      { type: 'key', key: '0' },
    )
    expect(s.splits).toEqual(two('75.00', '25.00'))
  })
  it('own share: shares are left alone and validation flags the mismatch', () => {
    const s = reduce(base({ amount: '10', ownShare: true, paidBy: null, splits: two('6.00', '4.00') }), { type: 'key', key: '0' })
    expect(s.splits).toEqual(two('6.00', '4.00'))
  })
  it('a scanned total also recomputes', () => {
    const s = reduce(base({ amount: '10', splitOn: true, splitMode: 'equal', splits: two('5.00', '5.00') }), {
      type: 'applyScan', householdCurrency: 'EUR', today: '2026-10-07',
      result: { amount: 20, currency: null, date: null, merchant: null, category_id: null } as never,
    })
    expect(s.splits).toEqual(two('10.00', '10.00'))
  })
  it('setSplit keeps what was typed, so a Percent split reopens with its percents', () => {
    const s = reduce(base(), { type: 'setSplit', on: true, mode: 'percent', splits: two('7.50', '2.50'), typed: { u2: '25' } })
    expect(s.splitTyped).toEqual({ u2: '25' })
  })
})
