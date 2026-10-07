import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { query } from './fixtures'

vi.mock('../settings/hooks', () => ({
  useBuckets: () => query([{ id: 'b1', name: 'Daily' }, { id: 'b2', name: 'Trip' }]),
  useCategories: () => query([{ id: 'c1', name: 'Groceries', color: '#000', icon: '🛒', is_default: false, system_key: null, locked: false, expense_count: 0, rule_count: 0 }]),
}))

import { parseFilters, writeFilters } from './filters'
import { RangeSheet } from './RangeSheet'

describe('filters', () => {
  it('round-trips through the URL', () => {
    const p = writeFilters(new URLSearchParams('p=last_month'), { bucketIds: ['b1', 'b2'], categoryIds: [] })
    expect(p.toString()).toBe('p=last_month&bucket_ids=b1%2Cb2')
    expect(parseFilters(p)).toEqual({ bucketIds: ['b1', 'b2'], categoryIds: [] })
  })
})

describe('RangeSheet', () => {
  const base = { open: true, onClose: vi.fn(), initialFrom: '2026-10-01', initialTo: '2026-10-06', filters: { bucketIds: [], categoryIds: [] }, onReset: vi.fn() }

  it('applies a custom range and chips', () => {
    const onApply = vi.fn()
    render(<RangeSheet {...base} onApply={onApply} />)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Daily' }))
    fireEvent.click(screen.getByRole('button', { name: 'Groceries' }))
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith({ preset: 'custom', from: '2026-09-01', to: '2026-10-06' }, { bucketIds: ['b1'], categoryIds: ['c1'] })
  })

  it('refuses From after To and an empty date', () => {
    const onApply = vi.fn()
    render(<RangeSheet {...base} onApply={onApply} />)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-10-09' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByText('From must be on or before To.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByText('Pick both dates.')).toBeInTheDocument()
    expect(onApply).not.toHaveBeenCalled()
  })

  it('Reset clears', () => {
    const onReset = vi.fn()
    render(<RangeSheet {...base} onReset={onReset} onApply={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(onReset).toHaveBeenCalled()
  })

  it('reopening starts again from what it opens with', () => {
    const { rerender } = render(<RangeSheet {...base} onApply={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
    rerender(<RangeSheet {...base} open={false} onApply={vi.fn()} />)
    rerender(<RangeSheet {...base} onApply={vi.fn()} />)
    expect(screen.getByLabelText('From')).toHaveValue('2026-10-01')
  })
})
