import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SplitSheet, type SplitSheetProps } from './SplitSheet'
import type { Member } from './types'

afterEach(cleanup)

const MEMBERS: Member[] = [
  { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'u2', role: 'member', display_name: 'Maria', username: 'm', avatar_color: null },
]
const props = (over: Partial<SplitSheetProps> = {}): SplitSheetProps => ({
  open: true, onClose: () => {}, variant: 'split', totalCents: 1001, currency: 'EUR', members: MEMBERS,
  payerId: 'u2', initial: { mode: 'equal', shares: [] }, onDone: vi.fn(), ...over,
})

it('equal: shares to the cent with the leftover cent on the payer; Done sends every member', () => {
  const p = props()
  render(<SplitSheet {...p} />)
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'equal', shares: [{ user_id: 'u1', amount: '5.00' }, { user_id: 'u2', amount: '5.01' }] })
})

it('amounts: the payer covers the rest; Done is disabled when shares exceed the total', () => {
  const p = props({ totalCents: 1000, payerId: 'u1' })
  render(<SplitSheet {...p} />)
  fireEvent.click(screen.getByRole('button', { name: 'Amounts' }))
  const maria = screen.getByLabelText('Maria amount')
  fireEvent.change(maria, { target: { value: '12.00' } })
  expect(screen.getByRole('button', { name: 'Done' })).toBeDisabled()
  fireEvent.change(maria, { target: { value: '3.50' } })
  expect(screen.getByText('Giorgos covers the remaining €6.50')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'amounts', shares: [{ user_id: 'u1', amount: '6.50' }, { user_id: 'u2', amount: '3.50' }] })
})

it('percent: rounded down, the payer takes the remainder', () => {
  const p = props({ totalCents: 1000, payerId: 'u1' })
  render(<SplitSheet {...p} />)
  fireEvent.click(screen.getByRole('button', { name: 'Percent' }))
  fireEvent.change(screen.getByLabelText('Maria percent'), { target: { value: '33.33' } })
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'percent', shares: [{ user_id: 'u1', amount: '6.67' }, { user_id: 'u2', amount: '3.33' }] })
})

it('own share: "Who paid what", Done only when the amounts add up to the total', () => {
  const p = props({ variant: 'own', payerId: null, totalCents: 1000, initial: { mode: 'amounts', shares: [] } })
  render(<SplitSheet {...p} />)
  expect(screen.getByRole('dialog', { name: 'Who paid what' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Giorgos amount'), { target: { value: '6' } })
  expect(screen.getByRole('button', { name: 'Done' })).toBeDisabled()
  expect(screen.getByText('Left to assign €4.00')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Maria amount'), { target: { value: '4' } })
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'amounts', shares: [{ user_id: 'u1', amount: '6.00' }, { user_id: 'u2', amount: '4.00' }] })
})
