import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ToggleRow } from './ToggleRow'

afterEach(cleanup)

it('is a switch named by its label and flips', () => {
  const onChange = vi.fn()
  render(<ToggleRow label="Count in forecast" hint="Turn off for one-offs" checked onChange={onChange} />)
  const sw = screen.getByRole('switch', { name: 'Count in forecast' })
  expect(sw).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByText('Turn off for one-offs')).toBeInTheDocument()
  fireEvent.click(sw)
  expect(onChange).toHaveBeenCalledWith(false)
})

it('disabled does not flip', () => {
  const onChange = vi.fn()
  render(<ToggleRow label="Split" checked={false} onChange={onChange} disabled />)
  fireEvent.click(screen.getByRole('switch', { name: 'Split' }))
  expect(onChange).not.toHaveBeenCalled()
})
