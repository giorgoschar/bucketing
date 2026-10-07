import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { resetTestEnv, setOnline } from '../../test/render'
import { todayLocal } from './dates'
import { loadDefaults } from './defaults'
import { goOffline, writes } from './testHelpers'
import { created, renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

const ready = () => screen.findByRole('button', { name: 'Budget: Day to day. Change' })
const press = (...keys: string[]) => keys.forEach((k) => fireEvent.click(screen.getByRole('button', { name: k })))

it('two-tap path: 3 then Save sends one POST with the stored defaults, today and a client_id', async () => {
  const { api } = await renderComposer()
  await ready()
  expect(screen.getByRole('button', { name: 'Category: Coffee. Change' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Payer: Giorgos. Change' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Method: Apple Pay. Change' })).toBeInTheDocument()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: 'Save 3 euro to Day to day' }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
  expect(writes(api)[0]).toMatchObject({
    method: 'POST',
    path: '/api/v1/transactions',
    body: {
      type: 'expense', amount: '3.00', currency: 'EUR', exchange_rate: '1', bucket_id: 'b-day', category_id: 'c-coffee',
      paid_by: 'u1', payment_method: 'apple_pay', payer_mode: 'single', transaction_date: todayLocal(), splits: [],
      exclude_from_settlement: false, client_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    },
  })
  expect(await screen.findByText('Saved €3.00 to Day to day')).toBeInTheDocument()
})

it('a double tap on Save, or Enter pressed twice, sends one POST (Review Focus 1)', async () => {
  let release: (() => void) | undefined
  const { api } = await renderComposer('/new', {
    routes: { 'POST /api/v1/transactions': () => new Promise<Response>((r) => { release = () => r(created()) }) },
  })
  await ready()
  fireEvent.keyDown(document.body, { key: '3' })
  // Wait for the typed amount to reach the Save button instead of racing the re-render.
  const save = await screen.findByRole('button', { name: 'Save 3 euro to Day to day' })
  fireEvent.click(save)
  fireEvent.click(save)
  fireEvent.keyDown(document.body, { key: 'Enter' })
  fireEvent.keyDown(document.body, { key: 'Enter' })
  await vi.waitFor(() => expect(release).toBeDefined())
  release!()
  await screen.findByText('home screen')
  expect(writes(api).filter((c) => c.path === '/api/v1/transactions')).toHaveLength(1)
})

it('first use: the budget pill is dashed "Choose a budget" and Save stays disabled', async () => {
  await renderComposer('/new', { defaults: null })
  const pill = await screen.findByRole('button', { name: 'Budget: Choose a budget. Change' })
  expect(pill).toHaveClass('pill--empty')
  press('3')
  expect(screen.getByRole('button', { name: /^Save 3 euro/ })).toBeDisabled()
  expect(screen.getByText('Choose a budget', { selector: '.composer__problem' })).toBeInTheDocument()
})

it('income: green state, Received by, optional budget, no method pill, transfer, no duplicate check', async () => {
  const { api } = await renderComposer()
  await ready()
  fireEvent.click(screen.getByRole('button', { name: 'Income' })) // 2a's Segmented: aria-pressed buttons
  expect(document.querySelector('.composer[data-type="income"]')).not.toBeNull()
  expect(screen.queryByRole('button', { name: /^Method:/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Received by: Giorgos. Change' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Budget: None. Change' })).toBeInTheDocument()
  press('7', '0', '0')
  fireEvent.click(screen.getByRole('button', { name: 'Save income 700 euro' }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ type: 'income', amount: '700.00', bucket_id: null, payment_method: 'transfer', paid_by: 'u1' })
  expect(api.calls.some((c) => c.path === '/api/v1/transactions/check-duplicate')).toBe(false)
})

it('cash from wallet: payer locked to you, over-stash blocked with the wallet amount', async () => {
  const { api } = await renderComposer('/new?mode=cash')
  expect(await screen.findByLabelText('Payer: You')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Payer:/ })).not.toBeInTheDocument()
  expect(await screen.findByText('Wallet: €50.00')).toBeInTheDocument()
  press('6', '0')
  expect(screen.getByRole('button', { name: /^Save 60 euro/ })).toBeDisabled()
  expect(screen.getByText('Your wallet has €50.00')).toBeInTheDocument()
  press('Delete last digit')
  fireEvent.click(screen.getByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash', paid_by: 'u1' })
})

it('offline: Save queues, closes with the on-phone toast, and still learns the defaults', async () => {
  await renderComposer()
  await ready()
  goOffline()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  expect(await screen.findByText("Saved on this phone. It will sync when you're back online.")).toBeInTheDocument()
  expect(screen.getByText('home screen')).toBeInTheDocument()
  expect(await db.queue.count()).toBe(1)
  expect((await loadDefaults('h1')).last?.payment_method).toBe('apple_pay')
})

const DUP = { id: 't7', amount: 3, currency: 'EUR', date: '2026-10-06', notes: null, merchant: 'Coffee Island', bucket: 'Day to day', paid_by: 'Maria', same_bucket: true }

it('a likely duplicate stops the save; "Save anyway" sends it', async () => {
  const { api } = await renderComposer('/new', { routes: { 'GET /api/v1/transactions/check-duplicate': { duplicates: [DUP] } } })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  expect(await screen.findByText('Looks like Coffee Island €3.00 from 6 Oct. Save anyway?')).toBeInTheDocument()
  expect(writes(api)).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
})

it('"Open that one" drops the draft and goes to the match without asking', async () => {
  const { router } = await renderComposer('/new', { routes: { 'GET /api/v1/transactions/check-duplicate': { duplicates: [DUP] } } })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Open that one' }))
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/edit/t7'))
  expect(screen.queryByRole('dialog', { name: 'Discard this entry?' })).not.toBeInTheDocument()
})

it('receipt: disabled offline; uploaded after an online save; Retry after a failure', async () => {
  let fail = true
  const { api } = await renderComposer('/new', {
    routes: {
      'POST /api/v1/transactions/t1/receipt': () => (fail ? new Response('{}', { status: 500 }) : Response.json({ receipt_path: 'x.jpg' })),
    },
  })
  await ready()
  fireEvent.click(screen.getByRole('button', { name: /^More options/ }))
  const more = await screen.findByRole('dialog', { name: 'More' })
  act(() => setOnline(false))
  expect(within(more).getByText("Add the receipt later when you're online (Edit)")).toBeInTheDocument()
  expect(within(more).getByLabelText('Attach receipt')).toBeDisabled()
  act(() => setOnline(true))
  fireEvent.change(within(more).getByLabelText('Attach receipt'), {
    target: { files: [new File(['x'], 'r.jpg', { type: 'image/jpeg' })] },
  })
  expect(within(more).getByText('r.jpg')).toBeInTheDocument()
  fireEvent.click(within(more).getByRole('button', { name: 'Done' }))
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  expect(await screen.findByText("Saved. The receipt didn't upload.")).toBeInTheDocument()
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await vi.waitFor(() => expect(api.calls.filter((c) => c.path === '/api/v1/transactions/t1/receipt')).toHaveLength(2))
})

it('Undo on the saved toast deletes the new entry', async () => {
  const { api } = await renderComposer('/new', { routes: { 'DELETE /api/v1/transactions/t1': () => new Response(null, { status: 204 }) } })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
  await vi.waitFor(() =>
    expect(writes(api).map((c) => `${c.method} ${c.path}`)).toEqual(['POST /api/v1/transactions', 'DELETE /api/v1/transactions/t1']),
  )
})

it('closing asks "Discard this entry?" only when something was typed', async () => {
  const { router } = await renderComposer()
  await ready()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  await screen.findByText('home screen')
  act(() => { void router.navigate('/new') })
  await ready()
  press('5')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Discard this entry?' })).getByRole('button', { name: 'Keep editing' }))
  expect(screen.getByText('Amount 5.00 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Discard this entry?' })).getByRole('button', { name: 'Discard' }))
  await screen.findByText('home screen')
})

it('a 400 on save keeps the composer open with everything kept', async () => {
  const { api } = await renderComposer('/new', {
    routes: { 'POST /api/v1/transactions': () => Response.json({ detail: 'Unknown category.' }, { status: 400 }) },
  })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  await vi.waitFor(() => expect(writes(api)).toHaveLength(1))
  expect(await screen.findByText('Unknown category.')).toBeInTheDocument() // 2a's useAction toast
  expect(screen.getByText('Amount 3.00 euro')).toBeInTheDocument()
  expect(screen.queryByText('home screen')).not.toBeInTheDocument()
})

it('merchant: suggestions after 2 characters, and the keypad hides while typing', async () => {
  await renderComposer()
  await ready()
  const input = screen.getByPlaceholderText('Where? (optional)')
  fireEvent.focus(input)
  expect(screen.queryByRole('button', { name: '3' })).not.toBeInTheDocument()
  fireEvent.change(input, { target: { value: 'Cof' } })
  fireEvent.click(await screen.findByRole('option', { name: 'Coffee Island' }))
  expect(input).toHaveValue('Coffee Island')
  fireEvent.blur(input)
  expect(screen.getByRole('button', { name: '3' })).toBeInTheDocument()
})

it('Enter on a focused button activates that button, never Save: Enter on ✕ closes and does not save', async () => {
  const { api } = await renderComposer()
  await ready()
  fireEvent.keyDown(document.body, { key: '3' })
  const close = screen.getByRole('button', { name: 'Close' })
  close.focus()
  fireEvent.keyDown(close, { key: 'Enter' })
  await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
  expect(api.calls.filter((c) => c.path === '/api/v1/transactions/check-duplicate' || c.method === 'POST')).toHaveLength(0)
  fireEvent.click(close) // what the browser does for Enter on a focused button
  expect(await screen.findByRole('dialog', { name: 'Discard this entry?' })).toBeInTheDocument()
  expect(writes(api).filter((c) => c.path === '/api/v1/transactions')).toHaveLength(0)
  // Enter on the page itself still saves.
  fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
  fireEvent.keyDown(document.body, { key: 'Enter' })
  await screen.findByText('home screen')
  expect(writes(api).filter((c) => c.path === '/api/v1/transactions')).toHaveLength(1)
})

it('merchant suggestions are a keyboard combobox: arrows move, Enter picks, Escape closes the list', async () => {
  const { api } = await renderComposer()
  await ready()
  const input = screen.getByRole('combobox', { name: 'Merchant' })
  fireEvent.focus(input)
  fireEvent.change(input, { target: { value: 'Cof' } })
  const option = await screen.findByRole('option', { name: 'Coffee Island' })
  expect(input).toHaveAttribute('aria-expanded', 'true')
  expect(input).toHaveAttribute('aria-controls', screen.getByRole('listbox', { name: 'Recent places' }).id)
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  expect(input).toHaveAttribute('aria-activedescendant', option.id)
  expect(option).toHaveAttribute('aria-selected', 'true')
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(input).toHaveValue('Coffee Island')
  expect(writes(api)).toHaveLength(0) // picking is not saving
  fireEvent.change(input, { target: { value: 'Cof' } })
  expect(await screen.findByRole('listbox', { name: 'Recent places' })).toBeInTheDocument()
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(screen.queryByRole('listbox', { name: 'Recent places' })).not.toBeInTheDocument()
  expect(input).toHaveValue('Cof')
})
