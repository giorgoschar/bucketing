import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BulkBar } from './BulkBar'

afterEach(cleanup)

const actions = ['Bucket', 'Category', 'Payer', 'Method'].map((label) => ({ label, onClick: vi.fn() }))

describe('BulkBar', () => {
  it('is labelled for its count', () => {
    render(<BulkBar count={3} actions={actions} />)
    expect(screen.getByRole('toolbar', { name: 'Bulk actions for 3 selected' })).toBeInTheDocument()
  })

  it('is disabled offline with the reason', () => {
    render(<BulkBar count={3} actions={actions} disabled disabledReason="Needs a connection" />)
    expect(screen.getByText('Needs a connection')).toBeInTheDocument()
    for (const name of ['Bucket', 'Category', 'Payer', 'Method']) expect(screen.getByRole('button', { name })).toBeDisabled()
  })
})
