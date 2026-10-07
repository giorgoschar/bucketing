import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { setSignInNotice } from './notice'
import { SignIn } from './SignIn'

afterEach(() => { cleanup(); sessionStorage.clear() })

it('shows a one-shot notice once', () => {
  setSignInNotice('Password changed. Sign in again.')
  render(<SignIn result={{ error: null, linked: false }} />)
  expect(screen.getByRole('status')).toHaveTextContent('Password changed. Sign in again.')
  cleanup()
  render(<SignIn result={{ error: null, linked: false }} />)
  expect(screen.queryByText('Password changed. Sign in again.')).toBeNull()
})
