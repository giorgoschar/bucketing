import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router'
import { TabBar } from './TabBar'
import { SignIn } from '../session/SignIn'
import { readAuthResult } from '../session/authMessages'

afterEach(() => cleanup())

it('tab bar has four labelled tabs and the Add button, with the current one marked', () => {
  render(<MemoryRouter initialEntries={['/plan']}><TabBar /></MemoryRouter>)
  const links = screen.getAllByRole('link')
  expect(links.map((l) => l.getAttribute('aria-label') ?? l.textContent)).toEqual([
    'Home', 'Activity', 'Add', 'Plan', 'Insights',
  ])
  expect(screen.getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current')
  expect(screen.getByRole('link', { name: 'Add' })).toHaveAttribute('href', '/new')
})

it('sign-in links to the passkey flow and maps auth_error codes', () => {
  render(<SignIn result={readAuthResult('?auth_error=not_linked')} />)
  expect(screen.getByRole('link', { name: /Sign in with Face ID/ })).toHaveAttribute('href', '/app/auth/login')
  expect(screen.getByRole('alert')).toHaveTextContent('This passkey isn’t linked yet.')
})

it('sign-in falls back to a generic message and shows the linked status', () => {
  render(<SignIn result={readAuthResult('?auth_error=weird&linked=1')} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Sign-in failed. Try again.')
  expect(screen.getByRole('status')).toHaveTextContent('Passkey linked.')
})
