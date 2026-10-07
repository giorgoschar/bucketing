import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Bucket, Category, Member } from '../types'
import { BucketSheet } from './BucketSheet'
import { CategorySheet } from './CategorySheet'
import { CurrencySheet } from './CurrencySheet'
import { DateChips } from './DateSheet'
import { MethodSheet } from './MethodSheet'
import { PayerSheet } from './PayerSheet'

afterEach(cleanup)

const b = (id: string, name: string, over: Partial<Bucket> = {}): Bucket => ({
  id, name, kind: 'monthly', status: 'active', budget: null, start_date: null, end_date: null, show_income: false, ...over,
})
const BUCKETS = [
  b('b-day', 'Day to day'), b('b-old', 'Old budget', { status: 'archived' }), b('b-salary', 'Salary', { show_income: true }),
  b('b-crete', 'Crete', { kind: 'event', start_date: '2026-08-12', end_date: '2026-08-19' }),
]
const c = (id: string, name: string, over: Partial<Category> = {}): Category => ({
  id, name, icon: null, color: null, system_key: null, ...over,
})
const CATS = [c('c-coffee', 'Coffee'), c('c-eat', 'Eating out'), c('c-fuel', 'Fuel', { system_key: 'fuel' })]
const MEMBERS: Member[] = [
  { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'u2', role: 'member', display_name: 'Maria', username: 'm', avatar_color: null },
]

it('budget: active only; event range; expense has no None; picking closes', () => {
  const onPick = vi.fn()
  const onClose = vi.fn()
  render(<BucketSheet open onClose={onClose} buckets={BUCKETS} type="expense" selectedId="b-day" onPick={onPick} />)
  const sheet = screen.getByRole('dialog', { name: 'Budget' })
  expect(within(sheet).queryByRole('button', { name: /Old budget/ })).not.toBeInTheDocument()
  expect(within(sheet).queryByRole('button', { name: /^None/ })).not.toBeInTheDocument()
  expect(within(sheet).getByRole('button', { name: /Crete.*12–19 Aug/ })).toBeInTheDocument()
  expect(within(sheet).getByRole('button', { name: /Day to day/ })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(within(sheet).getByRole('button', { name: /Crete/ }))
  expect(onPick).toHaveBeenCalledWith('b-crete')
  expect(onClose).toHaveBeenCalled()
})

it('budget for income: None first, then income-tracking budgets only', () => {
  const onPick = vi.fn()
  render(<BucketSheet open onClose={() => {}} buckets={BUCKETS} type="income" selectedId={null} onPick={onPick} />)
  // Options carry aria-pressed; the sheet's own close button does not. "None" is the current choice.
  const options = screen.getAllByRole('button').filter((x) => x.hasAttribute('aria-pressed'))
  expect(options.map((x) => x.textContent)).toEqual(['None', 'Salary'])
  expect(screen.getByRole('button', { name: 'None' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'None' }))
  expect(onPick).toHaveBeenCalledWith(null)
})

it('category: suggested with its reason, recent, all, fuel hint, accent-free search', () => {
  render(
    <CategorySheet open onClose={() => {}} categories={CATS} recentIds={['c-eat', 'c-gone']}
      suggestion={{ id: 'c-coffee', reason: 'rule: coffee island' }} selectedId={null} onPick={() => {}} />,
  )
  expect(screen.getByRole('heading', { name: 'Suggested' })).toBeInTheDocument()
  expect(screen.getByText('rule: coffee island')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Recent' })).toBeInTheDocument()
  expect(screen.getByText('Asks for price per litre')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search categories'), { target: { value: 'FU' } })
  expect(screen.queryByRole('button', { name: /Coffee/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Fuel/ })).toBeInTheDocument()
})

it('payer: members, and own share only when allowed', () => {
  const onOwnShare = vi.fn()
  const { rerender } = render(
    <PayerSheet open onClose={() => {}} title="Payer" members={MEMBERS} selectedId="u1" ownShare={false} allowOwnShare onPick={() => {}} onOwnShare={onOwnShare} />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Each paid own share' }))
  expect(onOwnShare).toHaveBeenCalled()
  rerender(<PayerSheet open onClose={() => {}} title="Received by" members={MEMBERS} selectedId="u1" ownShare={false} allowOwnShare={false} onPick={() => {}} onOwnShare={onOwnShare} />)
  expect(screen.getByRole('dialog', { name: 'Received by' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Each paid own share' })).not.toBeInTheDocument()
})

it('method and currency lists', () => {
  const pickM = vi.fn()
  render(<MethodSheet open onClose={() => {}} selected="card" onPick={pickM} />)
  for (const n of ['Card', 'Cash', 'Apple Pay', 'Transfer', 'Other']) expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Apple Pay' }))
  expect(pickM).toHaveBeenCalledWith('apple_pay')
  cleanup()
  const pickC = vi.fn()
  render(<CurrencySheet open onClose={() => {}} selected="EUR" onPick={pickC} />)
  fireEvent.click(screen.getByRole('button', { name: 'GBP · pounds' }))
  expect(pickC).toHaveBeenCalledWith('GBP')
})

it('date chips: today, yesterday, the day before, no future dates', () => {
  const onPick = vi.fn()
  render(<DateChips value="2026-10-07" today="2026-10-07" onPick={onPick} />)
  expect(screen.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Mon 5 Oct' }))
  expect(onPick).toHaveBeenLastCalledWith('2026-10-05')
  const input = screen.getByLabelText('Pick a date')
  expect(input).toHaveAttribute('max', '2026-10-07')
  fireEvent.change(input, { target: { value: '2026-10-09' } })
  expect(onPick).toHaveBeenCalledTimes(1)
})
