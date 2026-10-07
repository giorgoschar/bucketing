import { describe, expect, it } from 'vitest'
import { copyOf, firstProblem, fromTransaction, isDirtyNew, moreDirty, toCreateBody, toUpdateBody, validate } from './model'
import { blankState, type ComposerState, reduce } from './state'
import type { Txn } from './types'

const CTX = { householdCurrency: 'EUR', fuelCategoryId: 'c-fuel' }
const V = { ...CTX, today: '2026-10-07', stashCents: null, meId: 'u1' }
const expense = (over: Partial<ComposerState> = {}): ComposerState => ({
  ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'cid-1', meId: 'u1' }),
  amount: '4.1', bucketId: 'b-day', categoryId: 'c-coffee', ...over,
})

describe('toCreateBody: one test per row of the spec §4.10 field map', () => {
  it('type, amount (decimal string), currency, rate "1", date, client_id, settlement false', () => {
    expect(toCreateBody(expense(), CTX)).toMatchObject({
      type: 'expense', amount: '4.10', currency: 'EUR', exchange_rate: '1', transaction_date: '2026-10-07',
      client_id: 'cid-1', exclude_from_settlement: false, exclude_from_forecast: false, payer_mode: 'single',
      bucket_id: 'b-day', category_id: 'c-coffee', paid_by: 'u1', payment_method: 'card', splits: [], took_cash: false,
    })
  })
  it('blank merchant and notes send null; filled ones are trimmed', () => {
    expect(toCreateBody(expense({ merchant: '  ', notes: '' }), CTX)).toMatchObject({ merchant: null, notes: null })
    expect(toCreateBody(expense({ merchant: ' Lidl ', notes: ' milk ' }), CTX)).toMatchObject({ merchant: 'Lidl', notes: 'milk' })
  })
  it('income: bucket optional (null), received by, transfer', () => {
    const s = expense({ type: 'income', bucketId: null, paidBy: 'u2', method: 'transfer', amount: '700' })
    expect(toCreateBody(s, CTX)).toMatchObject({ type: 'income', bucket_id: null, paid_by: 'u2', payment_method: 'transfer', amount: '700.00', splits: [] })
  })
  it('foreign currency sends the typed rate', () => {
    expect(toCreateBody(expense({ currency: 'GBP', rate: '1,153' }), CTX)).toMatchObject({ currency: 'GBP', exchange_rate: '1.153' })
  })
  it('fuel sends the price only for the fuel category', () => {
    expect(toCreateBody(expense({ categoryId: 'c-fuel', fuelPrice: '1.789' }), CTX).fuel_price_per_litre).toBe('1.789')
    expect(toCreateBody(expense({ categoryId: 'c-coffee', fuelPrice: '1.789' }), CTX)).not.toHaveProperty('fuel_price_per_litre')
  })
  it('split sends every member share', () => {
    const splits = [{ user_id: 'u1', amount: '2.05' }, { user_id: 'u2', amount: '2.05' }]
    expect(toCreateBody(expense({ splitOn: true, splits }), CTX)).toMatchObject({ splits, payer_mode: 'single', paid_by: 'u1' })
  })
  it('own share: payer_mode own_share, paid_by null, splits', () => {
    const splits = [{ user_id: 'u1', amount: '3.00' }, { user_id: 'u2', amount: '1.10' }]
    expect(toCreateBody(expense({ ownShare: true, paidBy: null, splits }), CTX)).toMatchObject({ payer_mode: 'own_share', paid_by: null, splits })
  })
  it('cash from wallet: took_cash and take_from stash; bank; not tracked sends neither', () => {
    expect(toCreateBody(expense({ method: 'cash', tookFrom: 'stash', cashMode: true }), CTX)).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash' })
    expect(toCreateBody(expense({ method: 'cash', tookFrom: 'bank' }), CTX)).toMatchObject({ took_cash: true, take_from: 'bank' })
    const none = toCreateBody(expense({ method: 'cash', tookFrom: 'none' }), CTX)
    expect(none.took_cash).toBe(false)
    expect(none).not.toHaveProperty('take_from')
  })
  it('count in forecast off sends exclude_from_forecast true', () => {
    expect(toCreateBody(expense({ countInForecast: false }), CTX).exclude_from_forecast).toBe(true)
  })
  it('a Fixed cost sends bucket_id null', () => {
    expect(toCreateBody(expense({ fixedCost: true, bucketId: null }), CTX).bucket_id).toBeNull()
  })
})

const STORED: Txn = {
  id: 't9', bucket_id: 'b-old', household_id: 'h1', amount: 64.2, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: 'u2', payer_mode: 'single', category_id: 'c-fuel', notes: 'full tank', transaction_date: '2026-10-01',
  receipt_path: 'abc.jpg', payment_method: 'card', merchant: 'Shell', fuel_price_per_litre: 1.789, fuel_litres: 35.886,
  exclude_from_forecast: true, exclude_from_settlement: true, recurring_bill_id: null, created_at: null,
  splits: [{ user_id: 'u1', amount: 32.1, is_settled: false }, { user_id: 'u2', amount: 32.1, is_settled: false }],
}

describe('edit', () => {
  it('fromTransaction then toUpdateBody round-trips a stored transaction unchanged', () => {
    const body = toUpdateBody(fromTransaction(STORED, { householdCurrency: 'EUR', meId: 'u1' }), CTX)
    expect(body).toEqual({
      type: 'expense', amount: '64.20', currency: 'EUR', exchange_rate: '1', bucket_id: 'b-old', category_id: 'c-fuel',
      merchant: 'Shell', paid_by: 'u2', payer_mode: 'single', payment_method: 'card', took_cash: false,
      transaction_date: '2026-10-01', notes: 'full tank', exclude_from_forecast: true, exclude_from_settlement: true,
      fuel_price_per_litre: '1.789', splits: [{ user_id: 'u1', amount: '32.10' }, { user_id: 'u2', amount: '32.10' }],
    })
    expect(body).not.toHaveProperty('client_id')
    expect(body).not.toHaveProperty('take_from')
  })
  it('edit sends fuel_price_per_litre null when cleared, and the own-share mode explicitly', () => {
    const s = { ...fromTransaction(STORED, { householdCurrency: 'EUR', meId: 'u1' }), fuelPrice: '' }
    expect(toUpdateBody(s, CTX).fuel_price_per_litre).toBeNull()
    const own = fromTransaction({ ...STORED, payer_mode: 'own_share', paid_by: null }, { householdCurrency: 'EUR', meId: 'u1' })
    expect(toUpdateBody(own, CTX)).toMatchObject({ payer_mode: 'own_share', paid_by: null })
  })
  it('a Fixed cost (no budget, linked to an item) is read-only and stays null', () => {
    const s = fromTransaction({ ...STORED, bucket_id: null, recurring_bill_id: 'r1' }, { householdCurrency: 'EUR', meId: 'u1' })
    expect(s.fixedCost).toBe(true)
    expect(toUpdateBody(s, CTX).bucket_id).toBeNull()
  })
  it('foreign currency keeps the stored rate', () => {
    const s = fromTransaction({ ...STORED, currency: 'GBP', exchange_rate: 1.153 }, { householdCurrency: 'EUR', meId: 'u1' })
    expect(toUpdateBody(s, CTX).exchange_rate).toBe('1.153')
  })
  it('copyOf makes a new entry dated today with a new client_id and no receipt', () => {
    const c = copyOf(fromTransaction(STORED, { householdCurrency: 'EUR', meId: 'u1' }), { clientId: 'cid-2', today: '2026-10-07' })
    expect(c).toMatchObject({ mode: 'new', editId: null, clientId: 'cid-2', date: '2026-10-07', storedReceiptPath: null, excludeFromSettlement: false, amount: '64.20' })
  })
})

describe('validate', () => {
  it('amount > 0, expense needs a budget, no future date', () => {
    const v = validate(expense({ amount: '', bucketId: null, date: '2026-10-08' }), V)
    expect(v.ok).toBe(false)
    expect(v.problems).toMatchObject({ amount: 'Enter an amount', bucket: 'Choose a budget', date: "Date can't be in the future" })
    expect(firstProblem(v.problems)).toBe('Choose a budget')
    expect(validate(expense({ type: 'income', bucketId: null }), V).ok).toBe(true)
    expect(validate(expense({ fixedCost: true, bucketId: null }), V).ok).toBe(true)
  })
  it('a foreign currency needs a valid rate', () => {
    expect(validate(expense({ currency: 'USD', rate: '' }), V).problems.rate).toBe('Enter the rate')
    expect(validate(expense({ currency: 'USD', rate: '0.92' }), V).ok).toBe(true)
  })
  it('a fuel price, if entered, is above 0', () => {
    expect(validate(expense({ categoryId: 'c-fuel', fuelPrice: '0' }), V).problems.fuel).toBe('Price must be above 0')
    expect(validate(expense({ categoryId: 'c-fuel', fuelPrice: '' }), V).ok).toBe(true)
  })
  it('splits within the total; own share must add up to the total within a cent', () => {
    const over = [{ user_id: 'u1', amount: '3.00' }, { user_id: 'u2', amount: '2.00' }]
    expect(validate(expense({ splitOn: true, splits: over }), V).problems.split).toBe('Fix the split')
    const short = [{ user_id: 'u1', amount: '2.00' }, { user_id: 'u2', amount: '2.00' }]
    expect(validate(expense({ ownShare: true, paidBy: null, splits: short }), V).problems.split).toMatch(/^Who paid what must add up to /)
    const ok = [{ user_id: 'u1', amount: '2.05' }, { user_id: 'u2', amount: '2.04' }]
    expect(validate(expense({ ownShare: true, paidBy: null, splits: ok }), V).ok).toBe(true)
  })
  it('my wallet: blocked above a known stash (converted), allowed when the stash is unknown', () => {
    const s = expense({ amount: '60', method: 'cash', tookFrom: 'stash', cashMode: true })
    expect(validate(s, { ...V, stashCents: 5000 }).problems.wallet).toBe('Your wallet has €50.00')
    expect(validate(s, V).ok).toBe(true)
    expect(validate({ ...s, currency: 'GBP', rate: '0.8' }, { ...V, stashCents: 5000 }).ok).toBe(true) // £60 at 0.8 = €48
  })
  it('cash taken must be paid by you (Review Focus 4)', () => {
    expect(validate(expense({ method: 'cash', tookFrom: 'bank', paidBy: 'u2' }), V).problems.payer).toBe('Cash taken must be paid by you')
    expect(validate(expense({ method: 'cash', tookFrom: 'none', paidBy: 'u2' }), V).ok).toBe(true)
  })
})

describe('dirty', () => {
  it('a new entry is dirty once it has an amount, merchant or notes', () => {
    expect(isDirtyNew(expense({ amount: '' }))).toBe(false)
    expect(isDirtyNew(expense({ amount: '0.' }))).toBe(false)
    expect(isDirtyNew(expense({ amount: '', notes: 'x' }))).toBe(true)
  })
  it('More shows a dot when something inside differs from its default', () => {
    const c = { ...CTX, today: '2026-10-07' }
    expect(moreDirty(expense(), c)).toBe(false)
    expect(moreDirty(expense({ date: '2026-10-06' }), c)).toBe(true)
    expect(moreDirty(expense({ countInForecast: false }), c)).toBe(true)
    expect(moreDirty(expense({ currency: 'GBP' }), c)).toBe(true)
  })
})

describe('editing the amount of a stored split (I1)', () => {
  const back3 = (s: ComposerState) => [0, 1, 2].reduce((x) => reduce(x, { type: 'key', key: 'back' }), s)
  it('the payer takes the remainder of the new amount', () => {
    const s = back3(fromTransaction({ ...STORED, paid_by: 'u1' }, { householdCurrency: 'EUR', meId: 'u1' }))
    expect(s.amount).toBe('64')
    expect(s.splits).toEqual([{ user_id: 'u1', amount: '31.90' }, { user_id: 'u2', amount: '32.10' }])
    expect(validate(s, { ...V, fuelCategoryId: null }).ok).toBe(true)
  })
  it('own share: shares stay and Save is blocked with a clear message', () => {
    const s = back3(fromTransaction({ ...STORED, payer_mode: 'own_share', paid_by: null }, { householdCurrency: 'EUR', meId: 'u1' }))
    expect(s.splits).toEqual([{ user_id: 'u1', amount: '32.10' }, { user_id: 'u2', amount: '32.10' }])
    const v = validate(s, { ...V, fuelCategoryId: null })
    expect(v.ok).toBe(false)
    expect(v.problems.split).toBe('Who paid what must add up to €64.00')
  })
})
