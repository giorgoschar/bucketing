import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { avatarInk, contrast } from './avatar'

const me = vi.hoisted(() => ({ value: { id: '1', username: 'g', display_name: 'Giorgos Ch', household_id: 'h', email: null, avatar_color: '#6366f1' as string | null } }))
vi.mock('../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: me.value, signOut: vi.fn() }) }))

import { TopBar } from './TopBar'

afterEach(cleanup)

it('the top-bar avatar initial reads at 4.5:1 on the user’s colour (it was 4.10:1 on indigo in dark mode)', () => {
  render(<TopBar title="Home" />)
  const initial = screen.getByRole('button', { name: 'Account' }).querySelector('.avatar') as HTMLElement
  expect(initial).toHaveTextContent('GC')
  expect(initial.style.color).not.toBe('')
  expect(contrast(avatarInk('#6366f1'), '#6366f1')).toBeGreaterThanOrEqual(4.5)
  expect(initial).toHaveStyle({ color: avatarInk('#6366f1'), background: '#6366f1' })
})

it('without a colour it uses the fallback class (ink on amber from the tokens)', () => {
  me.value = { ...me.value, avatar_color: null }
  render(<TopBar title="Home" />)
  const initial = screen.getByRole('button', { name: 'Account' }).querySelector('.avatar') as HTMLElement
  expect(initial).toHaveClass('avatar--fallback')
  expect(initial.getAttribute('style')).toBeNull()
})
