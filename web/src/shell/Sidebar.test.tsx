import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router'
import type { Session } from '../session/SessionProvider'
import { AppShell } from './AppShell'
import { stubDesktop } from './desktopStub'

// The panel itself is tested in AddPanel.test.tsx; here only that Add asks for it.
vi.mock('./AddSidePanel', () => ({ default: () => <p>add panel</p> }))
vi.mock('../offline/queue', () => ({ startReplayTriggers: () => () => {} }))
const session: Session = {
  status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {},
  me: { id: '1', username: 'g', household_id: 'h', display_name: 'Giorgos H', email: null, avatar_color: null },
}
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

// jsdom has no showModal.
HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function Screen() {
  const loc = useLocation()
  return (
    <div>
      <output data-testid="where">{loc.pathname + loc.search}</output>
      <input aria-label="Notes" />
      <textarea aria-label="Long notes" />
      <select aria-label="Pick"><option>a</option></select>
      <div contentEditable suppressContentEditableWarning aria-label="Rich" role="textbox" tabIndex={0} />
      {loc.search === '?dialog=1' && <dialog aria-label="Open one" open><button type="button">Inside</button></dialog>}
    </div>
  )
}

function at(url: string, desktop?: boolean) {
  const mq = desktop === undefined ? null : stubDesktop(desktop)
  const router = createMemoryRouter(
    [{ path: '/', element: <AppShell />, children: [{ path: '*', element: <Screen /> }] }],
    { initialEntries: [url] },
  )
  render(<RouterProvider router={router} />)
  return { router, mq }
}
const where = () => screen.getByTestId('where').textContent

it('phone: the tab bar renders and the sidebar does not', () => {
  at('/activity')
  const nav = screen.getByRole('navigation', { name: 'Main' })
  expect(within(nav).getByRole('link', { name: 'Add' })).toHaveAttribute('href', '/new')
  expect(screen.queryByText('Tameio')).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()
})

it('desktop: the sidebar renders and the tab bar does not', async () => {
  at('/activity', true)
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  expect(screen.getAllByRole('navigation', { name: 'Main' })).toHaveLength(1)
  expect(within(nav).getByText('Tameio')).toBeInTheDocument()
  expect(within(nav).queryByRole('link', { name: 'Add' })).not.toBeInTheDocument()
  expect(within(nav).getByRole('button', { name: 'Add' })).toBeInTheDocument()
  expect(within(nav).getAllByRole('link').map((l) => l.textContent)).toEqual(['Home', 'Activity', 'Plan', 'Insights', 'Settings'])
  expect(within(nav).getByRole('button', { name: 'Account' })).toBeInTheDocument()
})

it('desktop: the current destination has aria-current with the tab bar matching rules', async () => {
  at('/plan/items', true)
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  expect(within(nav).getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page')
  expect(within(nav).getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current') // "/" matches only itself
  expect(within(nav).getByRole('link', { name: 'Activity' })).not.toHaveAttribute('aria-current')
  cleanup()
  at('/settings/profile', true)
  const again = await screen.findByRole('navigation', { name: 'Main' })
  expect(within(again).getByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
})

it('desktop: the sidebar avatar opens the account sheet with Sign out', async () => {
  at('/', true)
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.click(within(nav).getByRole('button', { name: 'Account' }))
  expect(await screen.findByRole('button', { name: 'Sign out' })).toBeInTheDocument()
})

it('N opens the Add panel over the current screen on desktop', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.keyboard('n')
  expect(where()).toBe('/activity?add=1')
  expect(await screen.findByText('add panel')).toBeInTheDocument()
})

it('the Add button opens Add', async () => {
  at('/activity', true)
  await userEvent.click(await screen.findByRole('button', { name: 'Add' }))
  expect(where()).toBe('/activity?add=1')
})

it.each([
  ['an input', () => screen.getByLabelText('Notes')],
  ['a textarea', () => screen.getByLabelText('Long notes')],
  ['a select', () => screen.getByLabelText('Pick')],
  ['a contenteditable', () => screen.getByRole('textbox', { name: 'Rich' })],
])('N does nothing while %s has focus', async (_n, el) => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  act(() => el().focus())
  await userEvent.keyboard('n')
  expect(where()).toBe('/activity')
})

it('N does nothing while a dialog is open', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.keyboard('n')
  expect(where()).toBe('/activity?add=1') // control: nothing open, N works
  cleanup()
  at('/activity?dialog=1', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.keyboard('n')
  expect(where()).toBe('/activity?dialog=1')
})

it('N does nothing on the phone (no sidebar)', async () => {
  at('/activity')
  await userEvent.keyboard('n')
  expect(where()).toBe('/activity')
})
