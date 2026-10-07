import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, reply } from '../../../test/fakeApi'
import { cashMovement, cashRoutes, cashWallets, wallet, walletMember } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { formatMonthLabel } from '../../../ui/format'
import { Cash } from './Cash'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12)) // Wed 7 Oct 2026
})
afterEach(resetTestEnv)

const stashCard = () => screen.getByRole('region', { name: 'My stash' })
const card = (name: string) => screen.getByRole('article', { name: `${name}'s wallet` })

it('a positive stash shows the balance and "Only you see this"', async () => {
  fakeApi(cashRoutes())
  renderWithProviders(<Cash />, { route: '/plan?view=cash' })
  expect(await screen.findByText('€380.00')).toBeInTheDocument()
  expect(stashCard()).toHaveTextContent('Only you see this')
  expect(stashCard()).not.toHaveTextContent('Balance by the book')
  for (const name of ['Add', 'Take', 'Count']) expect(within(stashCard()).getByRole('button', { name })).toBeEnabled()
  expect(screen.queryByText(/may be .* short/)).not.toBeInTheDocument()
})

it('a negative stash reads "Balance by the book" and warns, with Count now', async () => {
  fakeApi(cashRoutes({ wallets: cashWallets({ stash: -20 }) }))
  renderWithProviders(<Cash />)
  expect(await screen.findByText('−€20.00')).toBeInTheDocument()
  expect(stashCard()).toHaveTextContent('Balance by the book')
  expect(screen.getByText('Your stash may be €20.00 short')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Count now' })).toBeEnabled()
})

it('a stash a hair below zero (−0.004) is not short', async () => {
  fakeApi(cashRoutes({ wallets: cashWallets({ stash: -0.004 }) }))
  renderWithProviders(<Cash />)
  await screen.findByRole('region', { name: 'My stash' })
  expect(stashCard()).not.toHaveTextContent('Balance by the book')
})

it('wallets: the month stepper, the viewer first, and the sum in words', async () => {
  fakeApi(cashRoutes())
  renderWithProviders(<Cash />)
  expect(await screen.findByRole('heading', { level: 3, name: 'Oct 2026' })).toBeInTheDocument()
  expect(screen.getByText('Household sees these')).toBeInTheDocument()
  const cards = screen.getAllByRole('article')
  expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual(["Giorgos's wallet", "Maria's wallet"])
  expect(card('Giorgos')).toHaveTextContent('Took €120.00 − Logged €75.00 = €45.00 not yet logged')
  expect(card('Maria')).toHaveTextContent('All logged')
  expect(card('Maria')).not.toHaveTextContent('not yet logged')
})

it('Took is carried + taken − put back; Logged is logged + outs; a still-have is subtracted as In hand', async () => {
  const me = walletMember({
    wallet: wallet({ carried: 10, taken: 130, put_back: 20, still_have: 15, logged: 70, outs: 5, not_yet_logged: 30 }),
  })
  fakeApi(cashRoutes({ wallets: cashWallets({ members: [me] }) }))
  renderWithProviders(<Cash />)
  expect(await screen.findByRole('article', { name: "Giorgos's wallet" }))
    .toHaveTextContent('Took €120.00 − In hand €15.00 − Logged €75.00 = €30.00 not yet logged')
})

it('the stepper asks for the new month', async () => {
  const fake = fakeApi(cashRoutes())
  renderWithProviders(<Cash />, { route: '/plan?view=cash' })
  await screen.findByRole('heading', { level: 3, name: 'Oct 2026' })
  fireEvent.click(screen.getByRole('button', { name: 'Previous month' }))
  expect(screen.getByRole('heading', { level: 3, name: formatMonthLabel('2026-09') })).toBeInTheDocument()
  await waitFor(() => {
    expect(fake.calls.filter((c) => c.path === '/api/v1/cash/wallets').map((c) => c.query.get('month'))).toContain('2026-09')
    expect(fake.calls.filter((c) => c.path === '/api/v1/cash/movements').map((c) => c.query.get('month'))).toContain('2026-09')
  })
})

it('Log it: only on your own card, only above 0.005, and it opens the composer with the amount', async () => {
  const maria = walletMember({ member_id: 'u2', name: 'Maria', is_me: false, wallet: wallet({ put_back: null, not_yet_logged: 30 }) })
  fakeApi(cashRoutes({ wallets: cashWallets({ members: [walletMember(), maria] }) }))
  const { router } = renderWithProviders(<Cash />)
  await screen.findByRole('article', { name: "Giorgos's wallet" })
  expect(within(card('Maria')).queryByRole('button', { name: 'Log it' })).not.toBeInTheDocument()
  expect(within(card('Maria')).queryByRole('button', { name: 'Still have' })).not.toBeInTheDocument()
  fireEvent.click(within(card('Giorgos')).getByRole('button', { name: 'Log it' }))
  expect(router.state.location.pathname).toBe('/new')
  expect(router.state.location.search).toBe('?mode=cash&take=none&amount=45.00')
})

it('no Log it at 0.004 not yet logged', async () => {
  const me = walletMember({ wallet: wallet({ not_yet_logged: 0.004 }) })
  fakeApi(cashRoutes({ wallets: cashWallets({ members: [me] }) }))
  renderWithProviders(<Cash />)
  expect(await screen.findByRole('article', { name: "Giorgos's wallet" })).toHaveTextContent('All logged')
  expect(screen.queryByRole('button', { name: 'Log it' })).not.toBeInTheDocument()
  expect(within(card('Giorgos')).getByRole('button', { name: 'Still have' })).toBeEnabled()
})

const MOVES = [
  cashMovement({ id: 'a', kind: 'take', stash_owner_id: null, amount: 40, movement_date: '2026-10-04', note: 'Laiki' }),
  cashMovement({ id: 'b', kind: 'take', stash_owner_id: 'u1', amount: 80, movement_date: '2026-10-02', transaction_id: 't5' }),
  cashMovement({ id: 'c', kind: 'take', stash_owner_id: 'u2', amount: 25, movement_date: '2026-10-05' }),
  cashMovement({ id: 'd', kind: 'stash_in', amount: 120, movement_date: '2026-10-01' }),
  cashMovement({ id: 'e', kind: 'put_back', amount: 10, movement_date: '2026-10-06' }),
  cashMovement({ id: 'f', kind: 'still_have', amount: 15, movement_date: '2026-10-07' }),
  cashMovement({ id: 'g', kind: 'out', amount: 5, movement_date: '2026-10-03' }),
  cashMovement({ id: 'h', kind: 'stash_count', amount: -20, movement_date: '2026-10-06', created_at: '2026-10-06T12:00:00' }),
  cashMovement({ id: 'i', user_id: 'u2', kind: 'take', stash_owner_id: 'u1', amount: 60, movement_date: '2026-10-03' }),
  cashMovement({ id: 'j', user_id: 'u2', kind: 'take', stash_owner_id: 'u1', amount: 30, movement_date: '2026-10-02', deleted: true }),
  cashMovement({ id: 'k', kind: 'stash_count', amount: 30, movement_date: '2026-09-30' }),
]

it('movement rows are worded as in the old list, newest first, with recounts and deleted takes', async () => {
  fakeApi(cashRoutes({ movements: MOVES }))
  renderWithProviders(<Cash />)
  const list = await screen.findByRole('list', { name: 'Movements' })
  const titles = within(list).getAllByRole('listitem').map((li) => li.querySelector('.ui-row__title')?.textContent)
  expect(titles).toEqual([
    'Still have: €15.00',
    'Recounted your stash (−€20.00)',
    'Put back into your stash',
    'Took from Maria\'s stash',
    'Took from the bank',
    'Cash out',
    'Maria took €60.00 from your stash',
    'Took from your stash',
    'Maria took €30.00 from your stash (deleted)',
    'Added to your stash',
    'Recounted your stash (+€30.00)',
  ])
  const deleted = within(list).getByText('Maria took €30.00 from your stash')
  expect(deleted.tagName).toBe('S')
  expect(within(list).getByText('Took from the bank').closest('li')).toHaveTextContent('4 Oct · Laiki')
})

it('a row with transaction_id links to /activity/:id', async () => {
  fakeApi(cashRoutes({ movements: MOVES }))
  renderWithProviders(<Cash />)
  const list = await screen.findByRole('list', { name: 'Movements' })
  expect(within(list).getByRole('link', { name: 'Open the expense' })).toHaveAttribute('href', '/activity/t5')
})

it('tapping your own row, then Delete, sends DELETE; others\' rows are not tappable', async () => {
  const fake = fakeApi(cashRoutes({ movements: MOVES }))
  renderWithProviders(<Cash />)
  const list = await screen.findByRole('list', { name: 'Movements' })
  expect(within(list).queryByRole('button', { name: /Maria took/ })).not.toBeInTheDocument()
  fireEvent.click(within(list).getByRole('button', { name: /Took from the bank/ }))
  const sheet = await screen.findByRole('dialog', { name: 'Cash entry' })
  expect(sheet).toHaveTextContent('Delete this cash entry?')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Delete' }))
  await waitFor(() => expect(fake.callsTo('DELETE /api/v1/cash/movements/{movement_id}').map((c) => c.path))
    .toEqual(['/api/v1/cash/movements/a']))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('a take that logged an expense warns that the expense stays', async () => {
  fakeApi(cashRoutes({ movements: MOVES }))
  renderWithProviders(<Cash />)
  const list = await screen.findByRole('list', { name: 'Movements' })
  fireEvent.click(within(list).getByRole('button', { name: /Took from your stash/ }))
  expect(await screen.findByRole('dialog', { name: 'Cash entry' })).toHaveTextContent('Delete this take? The expense stays.')
})

it('a refused delete shows the server\'s 400 detail inside the sheet, which stays open', async () => {
  const fake = fakeApi(cashRoutes({ movements: MOVES }))
  fake.on('DELETE /api/v1/cash/movements/{movement_id}', () =>
    reply(400, { detail: 'Deleting this would leave your stash below zero.' }))
  renderWithProviders(<Cash />)
  const list = await screen.findByRole('list', { name: 'Movements' })
  fireEvent.click(within(list).getByRole('button', { name: /Added to your stash/ }))
  const sheet = await screen.findByRole('dialog', { name: 'Cash entry' })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Delete' }))
  expect(await within(sheet).findByRole('alert')).toHaveTextContent('Deleting this would leave your stash below zero.')
  expect(screen.getByRole('dialog', { name: 'Cash entry' })).toBeInTheDocument()
})

it('an empty month says so', async () => {
  fakeApi(cashRoutes())
  renderWithProviders(<Cash />)
  expect(await screen.findByText('No cash movements in Oct 2026.')).toBeInTheDocument()
})

it('offline with a saved copy: the banner, and every write disabled with "Connect to change cash"', async () => {
  const fake = fakeApi(cashRoutes({ movements: MOVES }))
  const { unmount, client } = renderWithProviders(<Cash />)
  await screen.findByRole('list', { name: 'Movements' })
  await waitFor(() => expect(fake.calls.length).toBeGreaterThan(0))
  unmount()
  setOnline(false)
  fake.down()
  renderWithProviders(<Cash />, { client })
  expect(await screen.findByText('Offline · showing saved cash')).toBeInTheDocument()
  expect(screen.getAllByText('Connect to change cash').length).toBeGreaterThan(0)
  for (const name of ['Add', 'Take', 'Count']) expect(within(stashCard()).getByRole('button', { name })).toBeDisabled()
  expect(within(card('Giorgos')).getByRole('button', { name: 'Log it' })).toBeDisabled()
  expect(within(card('Giorgos')).getByRole('button', { name: 'Still have' })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Took from the bank/ })).toBeDisabled()
})

it('offline with nothing saved: an empty state, not a spinner', async () => {
  setOnline(false)
  const fake = fakeApi(cashRoutes())
  fake.down()
  renderWithProviders(<Cash />)
  expect(await screen.findByText('No saved cash yet. Connect once to load Cash.')).toBeInTheDocument()
  expect(screen.queryByRole('status', { name: 'Loading' })).not.toBeInTheDocument()
})
