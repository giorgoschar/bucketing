import { QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  cleanup()
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  for (const mod of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }]) {
    expect(fireEvent.keyDown(document.body, { key: '/', ...mod })).toBe(true) // not prevented
  }
  expect(field()).not.toHaveFocus()
})

it('Cmd K and Ctrl K do nothing, and keep the browser default, while a dialog is open', async () => {
  at('/activity?dialog=1', true)
  await screen.findByRole('navigation', { name: 'Main' })
  expect(fireEvent.keyDown(document.body, { key: 'k', metaKey: true })).toBe(true)
  expect(fireEvent.keyDown(document.body, { key: 'k', ctrlKey: true })).toBe(true)
  expect(field()).not.toHaveFocus()
  cleanup()
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  expect(fireEvent.keyDown(document.body, { key: 'k', ctrlKey: true })).toBe(false) // taken
  expect(field()).toHaveFocus()
})

it('Ctrl K works on a layout where the key is not "k" (it is the K key)', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  fireEvent.keyDown(document.body, { key: 'κ', code: 'KeyK', ctrlKey: true })
  expect(field()).toHaveFocus()
})

it('after Cmd K from a field, closing returns focus to that field; after a click it stays in the search field', async () => {
  at('/activity', true)
  await screen.findByRole('navigation', { name: 'Main' })
  act(() => screen.getByLabelText('Notes').focus())
  await userEvent.keyboard('{Meta>}k{/Meta}')
  expect(field()).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.getByLabelText('Notes')).toHaveFocus()
  await userEvent.click(field())
  await userEvent.keyboard('{Escape}')
  expect(field()).toHaveFocus()
  await userEvent.keyboard('x')
  expect(field()).toHaveValue('x') // typing reopens it
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
  expect(screen.queryByRole('listbox')).toBeNull()
  expect(field()).toHaveFocus() // the user clicked into it: it stays where they are
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

it('a 429 shows the device groups and the one quiet line', async () => {
  const api = fakeApi(searchRoutes())
  api.on('GET /api/v1/insights/statements', () => statementList())
  api.on('GET /api/v1/search' as never, (() => new Response(JSON.stringify({ detail: 'x' }), { status: 429 })) as never)
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'dark')
  expect(await screen.findByText('Couldn’t search entries, bills and pantry right now.')).toBeInTheDocument()
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

// ---------------- Fix round 1 ----------------

it('Enter only opens a result of the text in the field (clear, then retype fast)', async () => {
  fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  await screen.findByRole('listbox')
  await userEvent.clear(field())
  await userEvent.type(field(), 'da')
  expect(screen.queryByRole('listbox')).toBeNull()
  await userEvent.keyboard('{Enter}')
  expect(where()).toBe('/')
})

it('the highlighted result is scrolled into view', async () => {
  fakeApi(searchRoutes())
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  await screen.findByRole('listbox')
  await userEvent.keyboard('{ArrowDown}{ArrowDown}')
  expect(scroll).toHaveBeenLastCalledWith({ block: 'nearest' })
  expect(scroll.mock.contexts.at(-1)).toBe(document.getElementById(field().getAttribute('aria-activedescendant')!))
})

it('"See all in Activity" and the request carry the text URL-encoded', async () => {
  const api = fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'a&b%')
  const row = (await screen.findByText('See all in Activity')).closest('[role="option"]')!
  await userEvent.click(row)
  expect(where()).toBe('/activity?q=a%26b%25')
  expect(api.callsTo('GET /api/v1/search' as never)[0].query.get('q')).toBe('a&b%')
})

it('Greek text is searched; a long paste stops at 100 characters', async () => {
  const api = fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'Λιντλ')
  await screen.findByRole('listbox')
  expect(api.callsTo('GET /api/v1/search' as never)[0].query.get('q')).toBe('Λιντλ')
  await userEvent.clear(field())
  await userEvent.click(field())
  await userEvent.paste('x'.repeat(130))
  expect((field() as HTMLInputElement).value).toHaveLength(100)
})

it('the count is announced by a live region that is always there and only changes once results settle', async () => {
  fakeApi(searchRoutes())
  at('/', true)
  const input = await screen.findByRole('combobox', { name: 'Search' })
  const region = live()!
  expect(region).toBeInTheDocument()
  expect(region).toHaveAttribute('aria-live', 'polite')
  expect(region).toHaveTextContent('')
  await userEvent.type(input, 'lid')
  expect(region).toHaveTextContent('') // typing does not announce
  expect(live()).toBe(region) // not recreated
  await waitFor(() => expect(region).toHaveTextContent('3 results'))
})

it('one quiet line for a failed search and for a 429', async () => {
  for (const status of [500, 429]) {
    const api = fakeApi(searchRoutes())
    api.on('GET /api/v1/search' as never, (() => new Response(JSON.stringify({ detail: 'x' }), { status })) as never)
    at('/', true)
    await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'dark')
    expect(await screen.findByText('Couldn’t search entries, bills and pantry right now.')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Appearance' })).toBeInTheDocument()
    cleanup()
  }
})

it('a click on the panel (a group title) keeps the field focused and the panel open', async () => {
  fakeApi(searchRoutes())
  at('/', true)
  await userEvent.type(await screen.findByRole('combobox', { name: 'Search' }), 'lidl')
  await screen.findByRole('listbox')
  expect(fireEvent.mouseDown(screen.getByText('Pantry'))).toBe(false) // default prevented: focus stays
})

it('phone: the search is a modal dialog, Tab stays inside, and closing returns focus to the icon', async () => {
  fakeApi(searchRoutes())
  at('/activity', false)
  const icon = await screen.findByRole('button', { name: 'Search' })
  await userEvent.click(icon)
  const dialog = screen.getByRole('dialog', { name: 'Search' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  await userEvent.keyboard('lidl')
  await screen.findByRole('listbox')
  await userEvent.tab()
  await userEvent.tab()
  expect(dialog.contains(document.activeElement)).toBe(true)
  await userEvent.tab({ shift: true })
  await userEvent.tab({ shift: true })
  expect(dialog.contains(document.activeElement)).toBe(true)
  await userEvent.keyboard('{Escape}{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull())
  await waitFor(() => expect(screen.getByRole('button', { name: 'Search' })).toHaveFocus())
})
