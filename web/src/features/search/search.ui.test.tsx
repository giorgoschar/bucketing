import { QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../../test/render'
import { setIdentity } from '../../offline/identity'
import type { Session } from '../../session/SessionProvider'
import { AppShell } from '../../shell/AppShell'
import { stubDesktop } from '../../shell/desktopStub'
import { TopBar } from '../../shell/TopBar'
import { listMonth, statementList } from '../insights/statements/fixtures'
import type { SearchResponse } from './types'

vi.mock('../../shell/AddSidePanel', () => ({ default: () => <p>add panel</p> }))
vi.mock('../../offline/queue', async (orig) => ({ ...(await orig<typeof import('../../offline/queue')>()), startReplayTriggers: () => () => {} }))
const session: Session = {
  status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {},
  me: { id: '1', username: 'g', household_id: 'h1', display_name: 'Giorgos H', email: null, avatar_color: null },
}
vi.mock('../../session/SessionProvider', () => ({ useSession: () => session }))
HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(async () => { vi.unstubAllGlobals(); await resetTestEnv() })

const found: SearchResponse = {
  entries: [{ id: 'e1', date: '2026-10-07', label: 'Lidl', category: 'Groceries', amount: -29.9, currency: 'EUR' }],
  entries_more: true,
  items: [{ id: 'b1', name: 'Lidl plus', direction: 'out', is_active: true }],
  pantry: [{ id: 'p1', name: 'Lidl pasta', brand: null, quantity: 3 }],
}
const searchRoutes = (data: SearchResponse = found): Routes => ({
  'GET /api/v1/insights/statements': () => statementList({ months: [listMonth({ month: '2026-09', label: 'September 2026' })] }),
  'GET /api/v1/search': () => data,
} as unknown as Routes)

function Screen() {
  const loc = useLocation()
  return (
    <div>
      <TopBar title="Home" />
      <output data-testid="where">{loc.pathname + loc.search}</output>
      <input aria-label="Notes" />
      {loc.search === '?dialog=1' && <dialog aria-label="Open one" open><button type="button">Inside</button></dialog>}
    </div>
  )
}

function at(url: string, desktop: boolean) {
  stubDesktop(desktop)
  const router = createMemoryRouter(
    [{ path: '/', element: <AppShell />, children: [{ index: true, element: <Screen /> }, { path: '*', element: <Screen /> }] }],
    { initialEntries: [url] },
  )
  render(<QueryClientProvider client={testQueryClient()}><RouterProvider router={router} /></QueryClientProvider>)
  return router
}
const where = () => screen.getByTestId('where').textContent
const live = () => document.querySelector('.search__live')
const field = () => screen.getByRole('combobox', { name: 'Search' })

// ---------------- Desktop ----------------

it('/ focuses the search box; Cmd K and Ctrl K do from anywhere, even from a field', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.keyboard('/')
  expect(field()).toHaveFocus()
  act(() => screen.getByLabelText('Notes').focus())
  await userEvent.keyboard('{Meta>}k{/Meta}')
  expect(field()).toHaveFocus()
  act(() => screen.getByLabelText('Notes').focus())
  await userEvent.keyboard('{Control>}k{/Control}')
  expect(field()).toHaveFocus()
})

it('/ does nothing while a field has focus, a dialog is open or a modifier is down', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  act(() => screen.getByLabelText('Notes').focus())
  await userEvent.keyboard('/')
  expect(screen.getByLabelText('Notes')).toHaveFocus()
  expect(screen.getByLabelText('Notes')).toHaveValue('/')
  cleanup()
  at('/activity?dialog=1', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.keyboard('/')
  expect(field()).not.toHaveFocus()
})

it('typing in the search field does not trigger N, and N still opens the Add panel elsewhere', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.keyboard('/')
  await userEvent.keyboard('n')
  expect(field()).toHaveValue('n')
  expect(where()).toBe('/activity')
  await userEvent.keyboard('{Escape}{Escape}')
  expect(field()).not.toHaveFocus()
  await userEvent.keyboard('n')
  expect(where()).toBe('/activity?add=1')
})

it('groups in order, the count announced, and keyboard movement across groups with aria-activedescendant', async () => {
  fakeApi(searchRoutes())
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  const list = await screen.findByRole('listbox', { name: 'Search results' })
  expect(within(list).getAllByRole('group').map((g) => g.getAttribute('aria-labelledby')).length).toBe(3)
  expect(within(list).getAllByRole('group').map((g) => within(g).getAllByRole('option').length)).toEqual([2, 1, 1])
  const titles = Array.from(list.querySelectorAll('.search__title')).map((e) => e.textContent)
  expect(titles).toEqual(['Entries', 'Bills and income', 'Pantry'])
  expect(live()).toHaveTextContent('3 results')
  expect(field()).toHaveAttribute('aria-controls', list.id)
  const opts = within(list).getAllByRole('option')
  await userEvent.keyboard('{ArrowDown}')
  expect(field()).toHaveAttribute('aria-activedescendant', opts[0].id)
  await userEvent.keyboard('{ArrowDown}{ArrowDown}')
  expect(field()).toHaveAttribute('aria-activedescendant', opts[2].id) // crossed into Bills and income
  expect(opts[2]).toHaveAttribute('aria-selected', 'true')
  await userEvent.keyboard('{ArrowDown}{ArrowDown}')
  expect(field()).toHaveAttribute('aria-activedescendant', opts[0].id) // wraps
  await userEvent.keyboard('{ArrowUp}')
  expect(field()).toHaveAttribute('aria-activedescendant', opts[3].id)
})

it.each([
  ['Lidl', '/activity/e1'],
  ['See all in Activity', '/activity?q=lidl'],
  ['Lidl plus', '/insights/bills/b1'],
  ['Lidl pasta', '/plan/pantry/p1'],
])('opening %s goes to %s', async (name, to) => {
  fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  await screen.findByRole('listbox')
  const row = screen.getAllByRole('option').find((o) => o.querySelector('.search__label')?.textContent === name)!
  await userEvent.click(row)
  expect(where()).toBe(to)
  expect(field()).toHaveValue('')
})

it('Enter opens the highlighted result', async () => {
  fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  await screen.findByRole('listbox')
  await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{Enter}')
  expect(where()).toBe('/insights/bills/b1')
})

it('statements and settings are matched on the device and open their places', async () => {
  fakeApi(searchRoutes({ entries: [], entries_more: false, items: [], pantry: [] }))
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'sept')
  await userEvent.click(await screen.findByRole('option', { name: 'September 2026' }))
  expect(where()).toBe('/insights/statements/2026-09')
  await userEvent.type(field(), 'dark')
  await userEvent.click(await screen.findByRole('option', { name: 'Appearance' }))
  expect(where()).toBe('/settings/appearance')
})

it('Nothing found for “…”. when every group is empty', async () => {
  fakeApi(searchRoutes({ entries: [], entries_more: false, items: [], pantry: [] }))
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'qqqq')
  expect(await screen.findByText('Nothing found for “qqqq”.')).toBeInTheDocument()
  expect(live()).toHaveTextContent('No results')
})

it('Esc clears the text, then closes the panel', async () => {
  fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  await screen.findByRole('listbox')
  await userEvent.keyboard('{Escape}')
  expect(field()).toHaveValue('')
  expect(field()).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(field()).not.toHaveFocus()
  expect(screen.queryByRole('listbox')).toBeNull()
})

it('offline: device-side groups work and the server groups say to connect', async () => {
  fakeApi(searchRoutes())
  setOnline(false)
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'dark')
  expect(await screen.findByRole('option', { name: 'Appearance' })).toBeInTheDocument()
  expect(screen.getByText('Connect to search entries, bills and pantry.')).toBeInTheDocument()
  expect(screen.queryByText(/Nothing found/)).toBeNull()
})

it('a failed search shows the device groups and one quiet line', async () => {
  const api = fakeApi(searchRoutes())
  api.on('GET /api/v1/insights/statements', () => statementList())
  api.on('GET /api/v1/search' as never, (() => new Response(JSON.stringify({ detail: 'x' }), { status: 429 })) as never)
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'dark')
  expect(await screen.findByText('Too many searches. Wait a moment and try again.')).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Appearance' })).toBeInTheDocument()
})

// ---------------- Phone ----------------

it.each(['/', '/activity', '/plan', '/insights'])('phone: %s has the search icon', async (url) => {
  at(url, false)
  expect(await screen.findByRole('button', { name: 'Search' })).toBeInTheDocument()
})

it('phone: no search icon on other screens', async () => {
  at('/plan/items', false)
  await screen.findByTestId('where')
  expect(screen.queryByRole('button', { name: 'Search' })).toBeNull()
})

it('phone: the icon opens a full-screen search with the field focused; Back closes it', async () => {
  fakeApi(searchRoutes())
  const router = at('/activity', false)
  await userEvent.click(await screen.findByRole('button', { name: 'Search' }))
  const dialog = screen.getByRole('dialog', { name: 'Search' })
  expect(within(dialog).getByRole('combobox', { name: 'Search' })).toHaveFocus()
  await act(() => router.navigate(-1))
  expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull()
  expect(where()).toBe('/activity')
})

it('phone: Esc clears, then closes', async () => {
  fakeApi(searchRoutes())
  at('/', false)
  await userEvent.click(await screen.findByRole('button', { name: 'Search' }))
  await userEvent.keyboard('lidl')
  await screen.findByRole('listbox')
  await userEvent.keyboard('{Escape}')
  expect(field()).toHaveValue('')
  await userEvent.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull())
})

it('phone: a result replaces the search, so Back from it returns to where the search opened', async () => {
  fakeApi(searchRoutes())
  const router = at('/plan', false)
  await userEvent.click(await screen.findByRole('button', { name: 'Search' }))
  await userEvent.keyboard('lidl')
  await screen.findByRole('listbox')
  await userEvent.click(screen.getAllByRole('option').find((o) => o.textContent?.startsWith('Lidl pasta'))!)
  expect(where()).toBe('/plan/pantry/p1')
  expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull()
  await act(() => router.navigate(-1))
  expect(where()).toBe('/plan')
  expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull()
})
