import { expect, it } from 'vitest'
import { item } from '../../../test/fixtures'
import { emptyItemForm, formToBody, itemToForm, pendingItem, validateItemForm } from './form'

it('editing keeps the fields this sheet does not show (a PUT replaces the row)', () => {
  const existing = item({
    payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24, contract_end_date: '2027-12-31',
    splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
  })
  expect(formToBody({ ...itemToForm(existing), name: 'Cosmote fibre' })).toMatchObject({
    name: 'Cosmote fibre', payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24,
    contract_end_date: '2027-12-31', splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
    rule_kind: 'monthly_day', rule_day: 9, amount: '38.90', start_date: '2026-01-09',
  })
})

it('an In item never sends a bucket, auto-pay or shares', () => {
  const f = { ...itemToForm(item({ bucket_id: 'b1', is_auto_pay: true, splits: [{ user_id: 'u1', amount: 38.9 }] })), direction: 'in' as const }
  expect(formToBody(f)).toMatchObject({ direction: 'in', bucket_id: null, is_auto_pay: false, splits: [], payer_mode: 'single' })
})

it('amounts: a comma becomes a dot, blank means variable', () => {
  const base = { ...emptyItemForm('2026-10-07', 'u1'), name: 'Electricity' }
  expect(formToBody({ ...base, amount: '86,4' }).amount).toBe('86.40')
  expect(formToBody({ ...base, amount: '' }).amount).toBeNull()
  expect(formToBody({ ...base, currency: ' usd ' }).currency).toBe('USD')
})

it('validation explains the first problem', () => {
  const ok = { ...emptyItemForm('2026-10-07', 'u1'), name: 'Rent' }
  expect(validateItemForm(ok)).toBeNull()
  expect(validateItemForm({ ...ok, name: '  ' })).toBe('Give the item a name.')
  expect(validateItemForm({ ...ok, amount: '12,345' })).toBe('Enter the amount like 38.90, or leave it blank for a variable amount.')
  expect(validateItemForm({ ...ok, currency: 'EU' })).toBe('Use a 3-letter currency code, like EUR.')
  expect(validateItemForm({ ...ok, end_date: '2026-01-01' })).toBe('The end date is before the start date.')
})

it('a new form starts today, on the monthly day of today, paid by me', () => {
  expect(emptyItemForm('2026-10-07', 'u1')).toMatchObject({
    id: null, direction: 'out', currency: 'EUR', start_date: '2026-10-07', paid_by_default: 'u1', is_active: true,
    rule: { kind: 'monthly_day', day: 7, adjust: 'none', everyMonths: 1 },
  })
})

it('pendingItem builds a complete row from a queued body', () => {
  const body = formToBody({ ...emptyItemForm('2026-10-07', 'u1'), name: 'Salary', direction: 'in', amount: '1500' })
  expect(pendingItem(body, 'pending-1')).toMatchObject({
    id: 'pending-1', name: 'Salary', direction: 'in', amount: 1500, next_entry: null, is_active: true, splits: [],
  })
})
