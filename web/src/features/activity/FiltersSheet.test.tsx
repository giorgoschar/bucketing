import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FiltersSheet } from './FiltersSheet'
import { REF } from './testing'

afterEach(cleanup)

const ITEMS = [{ id: 'r-cosmote', name: 'Cosmote', direction: 'out' }]

function setup(filter = {}) {
  const onApply = vi.fn()
  render(<FiltersSheet open filter={filter} refData={REF} items={ITEMS} onApply={onApply} onClose={() => {}} />)
  return onApply
}

describe('FiltersSheet', () => {
  it('maps "No bucket" to no_bucket, and amounts and dates to the API names', () => {
    const onApply = setup({ q: 'x' })
    fireEvent.change(screen.getByLabelText('Bucket'), { target: { value: '__none' } })
    fireEvent.change(screen.getByLabelText('Min €'), { target: { value: '10,5' } })
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
    fireEvent.change(screen.getByLabelText('Recurring item'), { target: { value: 'r-cosmote' } })
    fireEvent.click(screen.getByRole('button', { name: 'Show results' }))
    expect(onApply).toHaveBeenCalledWith({
      q: 'x', no_bucket: true, min_amount: '10,5', from_date: '2026-09-01', recurring_bill_id: 'r-cosmote',
    })
  })

  it('Reset keeps only the search', () => {
    const onApply = setup({ q: 'x', type: 'income', bucket_id: 'b-day' })
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(onApply).toHaveBeenCalledWith({ q: 'x' })
  })
})
