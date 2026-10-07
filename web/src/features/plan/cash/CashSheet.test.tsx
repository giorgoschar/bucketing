import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { type FakeApi, fakeApi, reply } from '../../../test/fakeApi'
import { cashRoutes, cashWallets, readRoutes, wallet, walletMember } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { Cash } from './Cash'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12)) // Wed 7 Oct 2026
})
afterEach(resetTestEnv)

const posts = (api: FakeApi) => api.calls.filter((c) => c.method === 'POST' && c.path === '/api/v1/cash/movements')

async function open(button: string, routes = cashRoutes()) {
  const api = fakeApi({ ...readRoutes(), ...routes })
  renderWithProviders(<Cash />, { route: '/plan?view=cash' })
  const stash = await screen.findByRole('region', { name: 'My stash' })
  fireEvent.click(within(stash).getByRole('button', { name: button }))
  return { api, sheet: await screen.findByRole('dialog') }
}
const type = (sheet: HTMLElement, label: string, value: string) =>
  fireEvent.change(within(sheet).getByLabelText(label), { target: { value } })

it('Take from my stash: "now → after", then the exact body', async () => {
  const { api, sheet } = await open('Take')
  expect(sheet).toHaveAccessibleName('Take cash')
  type(sheet, 'Amount', '40')
  const mine = within(sheet).getByRole('radio', { name: /My stash/ })
  expect(mine).toBeChecked()
  expect(mine.closest('label')).toHaveTextContent('€380.00 now → €340.00 after')
  type(sheet, 'Note (optional)', 'Laiki')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €40.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({
    kind: 'take', amount: '40.00', movement_date: '2026-10-07', note: 'Laiki', stash_owner_id: 'u1',
  })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it("Take from another member's stash: balance hidden, no spend toggle, stash_owner_id in the body", async () => {
  const { api, sheet } = await open('Take')
  const maria = within(sheet).getByRole('radio', { name: /Maria's stash/ })
  expect(maria.closest('label')).toHaveTextContent('Balance hidden')
  expect(maria.closest('label')).not.toHaveTextContent('notified')
  expect(within(sheet).getByRole('switch', { name: 'I spent it on…' })).toBeInTheDocument()
  fireEvent.click(maria)
  expect(within(sheet).queryByRole('switch', { name: 'I spent it on…' })).not.toBeInTheDocument()
  type(sheet, 'Amount', '500')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €500.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({ kind: 'take', amount: '500.00', movement_date: '2026-10-07', note: null, stash_owner_id: 'u2' })
})

it('Take from the bank: stash_owner_id null', async () => {
  const { api, sheet } = await open('Take')
  fireEvent.click(within(sheet).getByRole('radio', { name: /Bank or ATM/ }))
  type(sheet, 'Amount', '60')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €60.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toMatchObject({ kind: 'take', amount: '60.00', stash_owner_id: null })
})

it('the spend toggle sends the bucket and category, and the button says "and log it"', async () => {
  const { api, sheet } = await open('Take')
  type(sheet, 'Amount', '40')
  fireEvent.click(within(sheet).getByRole('switch', { name: 'I spent it on…' }))
  expect(within(sheet).getByLabelText('Budget')).toHaveValue('b1')
  fireEvent.change(within(sheet).getByLabelText('Category'), { target: { value: 'c1' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €40.00 and log it' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({
    kind: 'take', amount: '40.00', movement_date: '2026-10-07', note: null, stash_owner_id: 'u1',
    spend_bucket_id: 'b1', category_id: 'c1',
  })
})

it('the own-stash pre-check blocks the save and says why', async () => {
  const { api, sheet } = await open('Take')
  type(sheet, 'Amount', '380.01')
  expect(within(sheet).getByText('Not enough cash in your stash.')).toBeInTheDocument()
  expect(within(sheet).getByRole('button', { name: 'Take €380.01' })).toBeDisabled()
  type(sheet, 'Amount', '380')
  expect(within(sheet).queryByText('Not enough cash in your stash.')).not.toBeInTheDocument()
  expect(posts(api)).toHaveLength(0)
})

it("the server's refusal shows inline and the sheet stays open", async () => {
  const routes = cashRoutes()
  const { api, sheet } = await open('Take', {
    ...routes,
    'POST /api/v1/cash/movements': () => reply(400, { detail: 'Not enough cash in your stash.' }),
  } as typeof routes)
  type(sheet, 'Amount', '10')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €10.00' }))
  expect(await within(sheet).findByRole('alert')).toHaveTextContent('Not enough cash in your stash.')
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(posts(api)).toHaveLength(1)
})

it('Put back', async () => {
  const { api, sheet } = await open('Take')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Put back' }))
  expect(screen.getByRole('dialog')).toHaveAccessibleName('Put back')
  expect(within(sheet).queryByRole('radio')).not.toBeInTheDocument()
  type(sheet, 'Amount', '12,5')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Put back €12.50' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({ kind: 'put_back', amount: '12.50', movement_date: '2026-10-07', note: null })
})

it('Still have 0 is saved, with the not-yet-logged before → after', async () => {
  const api = fakeApi({ ...readRoutes(), ...cashRoutes() })
  renderWithProviders(<Cash />)
  const mine = await screen.findByRole('article', { name: "Giorgos's wallet" })
  fireEvent.click(within(mine).getByRole('button', { name: 'Still have' }))
  const sheet = await screen.findByRole('dialog', { name: 'Still have' })
  expect(sheet).toHaveTextContent('How much cash is in your wallet right now?')
  type(sheet, 'Amount', '15')
  expect(within(sheet).getByTestId('still-preview')).toHaveTextContent('Not yet logged €45.00 → €30.00')
  type(sheet, 'Amount', '0')
  expect(within(sheet).getByTestId('still-preview')).toHaveTextContent('Not yet logged €45.00 → €45.00')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save €0.00 in hand' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({ kind: 'still_have', amount: '0.00', movement_date: '2026-10-07', note: null })
})

it('Still have counts from the still-have already entered, floored at 0', async () => {
  const me = walletMember({ wallet: wallet({ still_have: 15, not_yet_logged: 30 }) })
  fakeApi({ ...readRoutes(), ...cashRoutes({ wallets: cashWallets({ members: [me] }) }) })
  renderWithProviders(<Cash />)
  const mine = await screen.findByRole('article', { name: "Giorgos's wallet" })
  fireEvent.click(within(mine).getByRole('button', { name: 'Still have' }))
  const sheet = await screen.findByRole('dialog', { name: 'Still have' })
  type(sheet, 'Amount', '20')
  expect(within(sheet).getByTestId('still-preview')).toHaveTextContent('Not yet logged €30.00 → €25.00')
  type(sheet, 'Amount', '100')
  expect(within(sheet).getByTestId('still-preview')).toHaveTextContent('Not yet logged €30.00 → €0.00')
})

it('a blank or malformed amount cannot be saved', async () => {
  const { sheet } = await open('Take')
  expect(within(sheet).getByRole('button', { name: 'Enter an amount' })).toBeDisabled()
  type(sheet, 'Amount', '12.345')
  expect(within(sheet).getByRole('button', { name: 'Enter an amount' })).toBeDisabled()
  expect(within(sheet).getByText('Enter an amount like 40 or 12,50')).toBeInTheDocument()
})

it('Add to stash: no segment row, title "Add to stash"', async () => {
  const { api, sheet } = await open('Add')
  expect(sheet).toHaveAccessibleName('Add to stash')
  expect(within(sheet).queryByRole('group', { name: 'Cash action' })).not.toBeInTheDocument()
  type(sheet, 'Amount', '120')
  type(sheet, 'Date', '2026-10-05')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add €120.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({ kind: 'stash_in', amount: '120.00', movement_date: '2026-10-05', note: null })
})

it('a comma decimal ("12,5") parses to 12.50', async () => {
  const { api, sheet } = await open('Take')
  fireEvent.click(within(sheet).getByRole('radio', { name: /Bank or ATM/ }))
  type(sheet, 'Amount', '12,5')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €12.50' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toMatchObject({ amount: '12.50' })
})

it('focus starts on the amount, Tab wraps from the last control to the first, Shift+Tab back, Esc closes', async () => {
  const { sheet } = await open('Take')
  expect(within(sheet).getByLabelText('Amount')).toHaveFocus()
  type(sheet, 'Amount', '5') // Save is disabled (so unfocusable) until an amount is typed
  const save = within(sheet).getByRole('button', { name: 'Take €5.00' })
  const close = within(sheet).getByRole('button', { name: 'Close' })
  save.focus()
  expect(save).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(close).toHaveFocus() // jsdom never moves focus on a synthetic Tab: only the trap can have done this
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(save).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

// Review M4: the connection drops while a sheet is open.
it('Save disables live when the device goes offline, and says why', async () => {
  const { sheet } = await open('Take')
  type(sheet, 'Amount', '5')
  expect(within(sheet).getByRole('button', { name: 'Take €5.00' })).toBeEnabled()
  act(() => setOnline(false))
  expect(within(sheet).getByRole('button', { name: 'Take €5.00' })).toBeDisabled()
  expect(within(sheet).getByText('Connect to change cash')).toBeInTheDocument()
  act(() => setOnline(true))
  expect(within(sheet).getByRole('button', { name: 'Take €5.00' })).toBeEnabled()
})
