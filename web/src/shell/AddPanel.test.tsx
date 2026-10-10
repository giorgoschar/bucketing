import { QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router'
import { cachePut, db, wipe } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { fakeApi } from '../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../test/render'
import { Compose } from '../screens/lazy'
import { type DefaultsRecord, defaultsKey } from '../features/composer/defaults'
import { dropDraft } from '../features/composer/draft'
import { pendingStore } from '../features/composer/hooks/pendingStore'
import { baseRoutes, DEFAULTS, TXN } from '../features/composer/testing'
import { goOffline, loose, writes } from '../features/composer/testHelpers'
import { resetTickedPrompt } from '../features/plan/pantry/tickedOffer'
import type { Session } from '../session/SessionProvider'
import { rememberScreen } from './addPanel'
import { AppShell } from './AppShell'
import { stubDesktop } from './desktopStub'
import { FullScreenShell } from './FullScreenShell'

vi.mock('../offline/queue', async (orig) => ({ ...(await orig<typeof import('../offline/queue')>()), startReplayTriggers: () => () => {} }))
const session: Session = {
  status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {},
  me: { id: 'u1', username: 'giorgos', household_id: 'h1', display_name: 'Giorgos', email: null, avatar_color: null },
}
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(async () => {
  cleanup()
  vi.unstubAllGlobals()
  resetTickedPrompt()
  await resetTestEnv()
})

function Screen({ name }: { name: string }) {
  const loc = useLocation()
  return (
    <div>
      <p>{name} screen</p>
      <output data-testid="where">{loc.pathname + loc.search}</output>
    </div>
  )
}
const where = () => screen.getByTestId('where').textContent
const panel = () => screen.getByRole('complementary', { name: /entry$/ })
const amount = () => within(panel()).getByRole('textbox', { name: 'Amount' }) as HTMLInputElement

/** The real shells and the real composer, on a desktop or a phone, with the API faked. */
async function setup(url: string, { desktop = true, routes = {}, defaults = DEFAULTS }: {
  desktop?: boolean; routes?: Record<string, unknown>; defaults?: DefaultsRecord
} = {}) {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
  rememberScreen('/', '') // module state: each test starts with no screen behind
  for (const k of ['new', 'edit:t9']) dropDraft(k) // …and no draft parked by a crossing that never finished
  await cachePut(defaultsKey('h1'), defaults)
  const api = fakeApi(loose({
    ...baseRoutes(),
    'GET /api/v1/transactions/t9': TXN,
    'PUT /api/v1/transactions/t9': () => ({ ...TXN, amount: 70 }),
    'DELETE /api/v1/transactions/t1': () => null,
    ...routes,
  }))
  const mq = stubDesktop(desktop)
  const full = (el: React.ReactNode) => <>{el}<Where /></>
  const router = createMemoryRouter(
    [
      {
        path: '/', element: <AppShell />,
        children: [
          { index: true, element: <Screen name="home" /> },
          { path: 'activity', element: <Screen name="activity" /> },
        ],
      },
      { element: <FullScreenShell />, children: [{ path: '/new', element: full(<Compose />) }, { path: '/edit/:id', element: full(<Compose />) }] },
    ],
    { initialEntries: [url] },
  )
  render(<QueryClientProvider client={testQueryClient()}><RouterProvider router={router} /></QueryClientProvider>)
  return { api, router, mq }
}
function Where() {
  const loc = useLocation()
  return <output data-testid="where">{loc.pathname + loc.search}</output>
}

it('opens from ?add=1 over the screen, with focus in the amount and no keypad', async () => {
  await setup('/?add=1')
  const field = await waitFor(() => amount())
  expect(field).toHaveFocus()
  expect(screen.getByText('home screen')).toBeInTheDocument() // the screen behind stays
  expect(screen.queryByRole('button', { name: 'Delete last digit' })).toBeNull()
  expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
})

it('a /new?mode=cash&take=none&amount=45.00 link opens the panel over the current screen with those values', async () => {
  const { router, api } = await setup('/activity')
  await screen.findByText('activity screen')
  await act(() => router.navigate('/new?mode=cash&take=none&amount=45.00'))
  await waitFor(() => expect(amount()).toHaveValue('45'))
  expect(where()).toBe('/activity?add=1&mode=cash&take=none&amount=45.00')
  expect(screen.getByText('activity screen')).toBeInTheDocument()
  expect(within(panel()).getByRole('button', { name: 'Cash from wallet' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.keyboard('{Enter}')
  await waitFor(() => expect(writes(api)).toHaveLength(1))
  expect(writes(api)[0].body).toMatchObject({ amount: '45.00', payment_method: 'cash', took_cash: false, paid_by: 'u1' })
})

it('saves from the keyboard, takes a comma, and stays open with the date, budget and payer kept', async () => {
  const user = userEvent.setup()
  const { api } = await setup('/?add=1')
  await waitFor(() => amount())
  // Pick a budget and a payer by typing (lists filter as you type, Enter picks), and yesterday.
  await user.click(within(panel()).getByRole('button', { name: /^Budget:/ }))
  await user.keyboard('car{Enter}')
  await user.click(within(panel()).getByRole('button', { name: /^Payer:/ }))
  await user.keyboard('mar{Enter}')
  await user.click(within(panel()).getByRole('button', { name: /^Date:/ }))
  await user.click(await screen.findByRole('button', { name: /^Yesterday/ }))
  expect(within(panel()).getByRole('button', { name: /^Date: Yesterday/ })).toBeInTheDocument()

  await user.type(amount(), '12,40')
  expect(amount()).toHaveValue('12.40')
  await user.type(within(panel()).getByRole('combobox', { name: 'Merchant' }), 'Lidl{Enter}') // Enter in a field saves
  await waitFor(() => expect(writes(api)).toHaveLength(1))
  expect(writes(api)[0].body).toMatchObject({ amount: '12.40', merchant: 'Lidl', bucket_id: 'b-car', paid_by: 'u2' })

  expect(await within(panel()).findByRole('status')).toHaveTextContent('Saved · €12.40 Lidl')
  expect(panel()).toBeInTheDocument() // stays open
  expect(amount()).toHaveValue('')
  expect(amount()).toHaveFocus()
  expect(within(panel()).getByRole('combobox', { name: 'Merchant' })).toHaveValue('')
  expect(within(panel()).getByRole('button', { name: /^Budget: Car/ })).toBeInTheDocument()
  expect(within(panel()).getByRole('button', { name: /^Payer: Maria/ })).toBeInTheDocument()
  expect(within(panel()).getByRole('button', { name: /^Date: Yesterday/ })).toBeInTheDocument()

  // ⌘/Ctrl+Enter saves from anywhere, and the second entry has its own client id.
  await user.type(amount(), '3')
  await user.keyboard('{Control>}{Enter}{/Control}')
  await waitFor(() => expect(writes(api)).toHaveLength(2))
  expect((writes(api)[1].body as { client_id: string }).client_id).not.toBe((writes(api)[0].body as { client_id: string }).client_id)
})

it('Undo in the panel deletes what was just saved', async () => {
  const user = userEvent.setup()
  const { api } = await setup('/?add=1')
  await waitFor(() => amount())
  await user.type(amount(), '5{Enter}')
  await user.click(await within(panel()).findByRole('button', { name: 'Undo' }))
  await waitFor(() => expect(api.callsTo('DELETE /api/v1/transactions/{txn_id}')).toHaveLength(1))
  expect(await within(panel()).findByRole('status')).toHaveTextContent('Undone')
})

it('Esc closes at once when nothing was typed, and asks first when the form is dirty', async () => {
  const user = userEvent.setup()
  await setup('/activity?add=1')
  await waitFor(() => amount())
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('complementary', { name: /entry$/ })).toBeNull())
  expect(where()).toBe('/activity')

  cleanup()
  await setup('/activity?add=1')
  await waitFor(() => amount())
  await user.type(amount(), '8')
  await user.keyboard('{Escape}')
  const ask = await screen.findByRole('dialog', { name: 'Discard this entry?' })
  await user.click(within(ask).getByRole('button', { name: 'Keep editing' }))
  expect(amount()).toHaveValue('8')
  await user.click(within(panel()).getByRole('button', { name: 'Close' }))
  await user.click(within(await screen.findByRole('dialog', { name: 'Discard this entry?' })).getByRole('button', { name: 'Discard' }))
  await waitFor(() => expect(screen.queryByRole('complementary', { name: /entry$/ })).toBeNull())
  expect(where()).toBe('/activity')
})

it('edit mode (?edit=<id>) closes after a save', async () => {
  const user = userEvent.setup()
  const { api } = await setup('/activity?edit=t9')
  await waitFor(() => expect(amount()).toHaveValue('64.20'))
  expect(panel()).toHaveAccessibleName('Edit entry')
  await user.clear(amount())
  await user.type(amount(), '70{Enter}')
  await waitFor(() => expect(api.callsTo('PUT /api/v1/transactions/{txn_id}')).toHaveLength(1))
  await waitFor(() => expect(screen.queryByRole('complementary', { name: /entry$/ })).toBeNull())
  expect(where()).toBe('/activity')
  expect(await screen.findByText('Saved changes')).toBeInTheDocument()
})

it('the offline queue works through the panel', async () => {
  const user = userEvent.setup()
  await setup('/?add=1')
  await waitFor(() => amount())
  goOffline()
  await user.type(amount(), '3{Enter}')
  expect(await within(panel()).findByRole('status')).toHaveTextContent("Saved on this phone. It will sync when you're back online.")
  expect(await db.queue.count()).toBe(1)
  expect(panel()).toBeInTheDocument()
})

it('the pantry prompt shows after a new expense saves through the panel', async () => {
  const user = userEvent.setup()
  await setup('/?add=1', { routes: { 'GET /api/v1/stock/summary': { low_count: 1, ticked_count: 3 } } })
  await waitFor(() => amount())
  await user.type(amount(), '4{Enter}')
  expect(await screen.findByRole('dialog', { name: '3 ticked pantry items' })).toBeInTheDocument()
})

it('the cash-from-wallet mode locks the payer to you and saves as cash', async () => {
  const user = userEvent.setup()
  const { api } = await setup('/?add=1')
  await waitFor(() => amount())
  await user.click(within(panel()).getByRole('button', { name: 'Cash from wallet' }))
  expect(within(panel()).getByRole('group', { name: 'Payer: You' })).toBeInTheDocument()
  await user.type(amount(), '6{Enter}')
  await waitFor(() => expect(writes(api)).toHaveLength(1))
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash', paid_by: 'u1' })
})

it('Tab order follows the spec: amount, type, description, budget, category, payer, method, date, More', async () => {
  const user = userEvent.setup()
  await setup('/?add=1')
  await waitFor(() => amount())
  const names: string[] = []
  for (let i = 0; i < 11; i += 1) {
    await user.tab()
    const el = document.activeElement as HTMLElement
    names.push(el.getAttribute('aria-label') ?? el.textContent ?? '')
  }
  const idx = (re: RegExp) => names.findIndex((n) => re.test(n))
  const order = [/^Currency/, /^Expense$/, /^Income$/, /^Merchant$/, /^Budget:/, /^Category:/, /^Payer:/, /^Method:/, /^Date:/, /^More options/]
    .map(idx)
  expect(order.every((i) => i >= 0)).toBe(true)
  expect([...order].sort((a, b) => a - b)).toEqual(order)
})

// Review focus 3: resizing across 1024 px with the panel open.
it('resize with a typed amount: the value survives, and the same address is the full-screen composer on the phone', async () => {
  const user = userEvent.setup()
  const { mq } = await setup('/activity?add=1')
  await waitFor(() => amount())
  await user.type(amount(), '7,5')
  await user.type(within(panel()).getByRole('combobox', { name: 'Merchant' }), 'Bakery')
  await act(() => mq.set(false))
  // The full-screen composer: its amount reads 7.50 and the merchant is still there.
  await waitFor(() => expect(where()).toBe('/new'))
  expect(await screen.findByText('Amount 7.50 euro')).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Merchant' })).toHaveValue('Bakery')
  expect(screen.queryByRole('complementary')).toBeNull()
  // And back: the panel over the screen the user was on, with the typed values.
  await act(() => mq.set(true))
  await waitFor(() => expect(amount()).toHaveValue('7.5'))
  expect(where()).toBe('/activity?add=1')
  expect(within(panel()).getByRole('combobox', { name: 'Merchant' })).toHaveValue('Bakery')
})

it('resizing does not interrupt a dirty form with a discard prompt', async () => {
  const user = userEvent.setup()
  const { mq } = await setup('/?add=1')
  await waitFor(() => amount())
  await user.type(amount(), '9')
  await act(() => mq.set(false))
  await waitFor(() => expect(where()).toBe('/new'))
  expect(screen.queryByRole('dialog', { name: 'Discard this entry?' })).toBeNull()
})

// Review focus 4: a reload with ?add=1 or ?edit=<id> in the URL.
it('cold load of /?add=1 and /activity?edit=<id> on desktop show the panel', async () => {
  await setup('/activity?edit=t9')
  await waitFor(() => expect(amount()).toHaveValue('64.20'))
  expect(screen.getByText('activity screen')).toBeInTheDocument()
})

it('cold load of /?add=1 on the phone lands on the full-screen composer, not a blank screen', async () => {
  await setup('/?add=1&amount=12', { desktop: false })
  expect(await screen.findByText('Amount 12.00 euro')).toBeInTheDocument()
  expect(where()).toBe('/new?amount=12')
})

it('cold load of /activity?edit=<id> on the phone lands on the full-screen edit composer', async () => {
  await setup('/activity?q=x&edit=t9', { desktop: false })
  expect(await screen.findByText('Amount 64.20 euro')).toBeInTheDocument()
  expect(where()).toBe('/edit/t9')
})

it('a cold /new on the phone is unchanged', async () => {
  await setup('/new?amount=3', { desktop: false })
  expect(await screen.findByText('Amount 3.00 euro')).toBeInTheDocument()
  expect(where()).toBe('/new?amount=3')
})

it('a cold /new on a desktop opens the panel over Home', async () => {
  await setup('/new?amount=3')
  await waitFor(() => expect(amount()).toHaveValue('3'))
  expect(where()).toBe('/?add=1&amount=3')
})
