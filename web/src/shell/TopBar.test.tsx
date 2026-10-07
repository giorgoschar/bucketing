import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { TopBar } from './TopBar'

afterEach(cleanup)

it('renders actions before the account button', () => {
  render(<TopBar title="Plan" actions={<button type="button">Items</button>} />)
  const buttons = screen.getAllByRole('button')
  expect(buttons.map((b) => b.getAttribute('aria-label') ?? b.textContent)).toEqual(['Items', 'Account'])
  expect(screen.getByRole('heading', { name: 'Plan' })).toBeInTheDocument()
})
