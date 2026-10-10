import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../../test/storage'
import { dismissBill, dismissedBills, resetBillDismissals } from './billDismiss'

installMemoryStorage()
const deny = () => { throw new Error('denied') }
const DENIED = { getItem: deny, setItem: deny, removeItem: deny, clear: deny, key: deny, length: 0 } as unknown as Storage
beforeEach(() => resetBillDismissals())
afterEach(() => resetBillDismissals())

it('remembers dismissed entry ids on this device', () => {
  expect(dismissedBills().has('e1')).toBe(false)
  dismissBill('e1')
  expect(dismissedBills().has('e1')).toBe(true)
  expect(dismissedBills().has('e2')).toBe(false)
  expect(JSON.parse(localStorage.getItem('tameio.billDismissed') ?? '[]')).toEqual(['e1'])
})

it('reads what an earlier session saved', () => {
  localStorage.setItem('tameio.billDismissed', JSON.stringify(['old']))
  resetBillDismissals()
  expect(dismissedBills().has('old')).toBe(true)
})

it('keeps the newest 100 only', () => {
  for (let i = 0; i < 120; i++) dismissBill(`e${i}`)
  const saved = JSON.parse(localStorage.getItem('tameio.billDismissed') ?? '[]') as string[]
  expect(saved).toHaveLength(100)
  expect(saved).toContain('e119')
  expect(saved).not.toContain('e0')
})

it('survives localStorage throwing: the dismissal lasts the session and nothing throws', () => {
  vi.stubGlobal('localStorage', DENIED)
  resetBillDismissals()
  expect(() => dismissedBills()).not.toThrow()
  expect(() => dismissBill('e1')).not.toThrow()
  expect(dismissedBills().has('e1')).toBe(true)
})

it('garbage in storage is ignored', () => {
  localStorage.setItem('tameio.billDismissed', '{not json')
  resetBillDismissals()
  expect(dismissedBills().size).toBe(0)
})
