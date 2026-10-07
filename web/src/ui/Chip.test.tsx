import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Chip } from './Chip'

afterEach(cleanup)

describe('Chip', () => {
  it('exposes its state with aria-pressed and shows the count', async () => {
    const onClick = vi.fn()
    render(<Chip label="No payer" count={3} pressed onClick={onClick} />)
    const chip = screen.getByRole('button', { name: /no payer 3/i })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(chip)
    expect(onClick).toHaveBeenCalledOnce()
  })
})
