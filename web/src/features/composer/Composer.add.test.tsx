import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { writes } from './testHelpers'
import { DEFAULTS, renderComposer, TXN } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

// Phase C spec §2.4 (the Add form). The desktop panel renders this same form; its cases are in shell/AddPanel.test.tsx.
const ready = () => screen.findByRole('button', { name: /^Budget:/ })
const pickMethod = async (name: string) => {
  fireEvent.click(screen.getByRole('button', { name: /^Method:/ }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Payment method' })).getByRole('button', { name }))
}
const press = (...digits: string[]) => digits.forEach((d) => fireEvent.click(screen.getByRole('button', { name: d })))

it('one Scan button opens a sheet with Receipt QR and Pantry barcode; the old chips are gone', async () => {
  await renderComposer('/new')
  await ready()
  expect(screen.queryByRole('button', { name: 'Scan receipt' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cash from wallet' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
  const sheet = within(await screen.findByRole('dialog', { name: 'Scan' }))
  expect(sheet.getByRole('button', { name: /^Receipt QR/ })).toBeInTheDocument()
  expect(sheet.getByRole('button', { name: /^Pantry barcode/ })).toBeInTheDocument()
})

it('income and edit have no Scan button', async () => {
  await renderComposer('/edit/t9', { routes: { 'GET /api/v1/transactions/t9': TXN } })
  await ready()
  expect(screen.queryByRole('button', { name: 'Scan' })).not.toBeInTheDocument()
})

it('the method list is Card, Cash, then the others', async () => {
  await renderComposer('/new')
  await ready()
  fireEvent.click(screen.getByRole('button', { name: /^Method:/ }))
  const names = within(await screen.findByRole('dialog', { name: 'Payment method' })).getAllByRole('button').filter((b) => b.classList.contains('ck-option')).map((b) => b.textContent)
  expect(names.slice(0, 2)).toEqual(['Card', 'Cash'])
  expect(names.slice(2).join()).toMatch(/Apple Pay.*Transfer.*Other/)
})

const took = () => within(screen.getByRole('group', { name: 'Took from' }))
const noCashPost = (api: { calls: { method: string; path: string }[] }) =>
  expect(api.calls.some((c) => c.method === 'POST' && c.path.startsWith('/api/v1/cash'))).toBe(false)

// Money safety (fix round 1, finding 1): Cash from the method sheet is "Not tracked", exactly as plain Cash was.
it('picking Cash shows "Took from" on Not tracked, leaves the payer free, and sends no take', async () => {
  const { api } = await renderComposer('/new')
  await ready()
  expect(screen.queryByRole('group', { name: 'Took from' })).not.toBeInTheDocument()
  await pickMethod('Cash')
  await screen.findByRole('group', { name: 'Took from' })
  expect(took().getByRole('button', { name: 'Not tracked' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: /^Payer:/ })).toBeInTheDocument()
  press('6')
  fireEvent.click(screen.getByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
  const body = writes(api)[0].body as Record<string, unknown>
  expect(body).toMatchObject({ payment_method: 'cash', took_cash: false })
  expect(body).not.toHaveProperty('take_from')
  noCashPost(api)
})

it('picking Cash, then My wallet, takes once from the wallet and locks the payer to you', async () => {
  const { api } = await renderComposer('/new')
  await ready()
  await pickMethod('Cash')
  await screen.findByRole('group', { name: 'Took from' })
  fireEvent.click(took().getByRole('button', { name: 'My wallet' }))
  expect(screen.getByLabelText('Payer: You')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Payer:/ })).not.toBeInTheDocument()
  expect(await screen.findByText('Wallet: €50.00')).toBeInTheDocument()
  press('6')
  fireEvent.click(screen.getByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash', paid_by: 'u1' })
})

it('a payer picked before My wallet becomes you when the wallet is chosen', async () => {
  const { api } = await renderComposer('/new')
  await ready()
  fireEvent.click(screen.getByRole('button', { name: /^Payer:/ }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Payer' })).getByRole('button', { name: /Maria/ }))
  await pickMethod('Cash')
  fireEvent.click(took().getByRole('button', { name: 'My wallet' }))
  press('6')
  fireEvent.click(screen.getByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ took_cash: true, take_from: 'stash', paid_by: 'u1' })
})

// Fix round 1, finding 2: the payer is locked only while a take is tracked.
it('Cash with Not tracked lets Maria be the payer; My wallet then Not tracked frees the chip again', async () => {
  const { api } = await renderComposer('/new?mode=cash')
  await ready()
  expect(screen.getByLabelText('Payer: You')).toBeInTheDocument()
  fireEvent.click(took().getByRole('button', { name: 'Not tracked' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Payer:/ }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Payer' })).getByRole('button', { name: /Maria/ }))
  press('6')
  fireEvent.click(screen.getByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: false, paid_by: 'u2' })
})

it('Cash pre-selected from the last entry is Not tracked and sends no take', async () => {
  const { api } = await renderComposer('/new', {
    defaults: { ...DEFAULTS, last: { ...DEFAULTS.last, payment_method: 'cash' } },
  })
  await ready()
  expect(screen.getByRole('button', { name: 'Method: Cash. Change' })).toBeInTheDocument()
  expect(took().getByRole('button', { name: 'Not tracked' })).toHaveAttribute('aria-pressed', 'true')
  press('4')
  fireEvent.click(screen.getByRole('button', { name: /^Save 4 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: false })
  expect(writes(api)[0].body).not.toHaveProperty('take_from')
})

it('?mode=cash is the wallet take with the payer locked, as before', async () => {
  const { api } = await renderComposer('/new?mode=cash&amount=6')
  await ready()
  expect(took().getByRole('button', { name: 'My wallet' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(await screen.findByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash', paid_by: 'u1' })
})

it('choosing Cash, then another method, takes the control away and sends no take', async () => {
  const { api } = await renderComposer('/new')
  await ready()
  await pickMethod('Cash')
  await screen.findByRole('group', { name: 'Took from' })
  fireEvent.click(took().getByRole('button', { name: 'My wallet' }))
  await pickMethod('Transfer')
  expect(screen.queryByRole('group', { name: 'Took from' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Payer:/ })).toBeInTheDocument()
  press('4')
  fireEvent.click(screen.getByRole('button', { name: /^Save 4 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'transfer', took_cash: false })
})

it('?mode=cash&take=none keeps "Not tracked" and picking Cash again does not reset it', async () => {
  const { api } = await renderComposer('/new?mode=cash&take=none&amount=12')
  await ready()
  expect(took().getByRole('button', { name: 'Not tracked' })).toHaveAttribute('aria-pressed', 'true')
  await pickMethod('Cash')
  expect(took().getByRole('button', { name: 'Not tracked' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: /^Save 12 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: false })
  expect(api.calls.some((c) => c.method === 'POST' && c.path.startsWith('/api/v1/cash'))).toBe(false)
})

it('a missing budget turns the chip amber, shows no second line, and stays Save\'s description', async () => {
  await renderComposer('/new', { defaults: null })
  const pill = await ready()
  expect(pill).toHaveClass('pill--attention')
  press('3')
  const save = screen.getByRole('button', { name: /^Save 3 euro/ })
  expect(save).toBeDisabled()
  const reason = document.getElementById(save.getAttribute('aria-describedby') ?? '')
  expect(reason).toHaveTextContent('Choose a budget')
  expect(reason).toHaveClass('ck-visually-hidden')
  expect(document.querySelector('.composer__problem')).toBeNull()
})

it('other reasons (a rate, the wallet) still show as a line', async () => {
  await renderComposer('/new?mode=cash&amount=60')
  await ready()
  expect(await screen.findByText('Your wallet has €50.00')).toHaveClass('composer__problem')
})

it('the currency is in More only, unless a foreign entry or a recent foreign entry is in play', async () => {
  await renderComposer('/new')
  await ready()
  expect(screen.queryByRole('button', { name: 'Currency: EUR. Change' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'More options' }))
  expect(within(await screen.findByRole('dialog', { name: 'More' })).getByRole('button', { name: 'Currency: EUR. Change' })).toBeInTheDocument()
})

it('the currency stays on the form when one of the last 20 entries was foreign, but not the 21st', async () => {
  const items = (n: number, foreignAt: number) =>
    Array.from({ length: n }, (_, i) => ({ ...TXN, id: `t${i}`, currency: i === foreignAt ? 'USD' : 'EUR' }))
  const page = (xs: unknown[]) => ({ total: xs.length, page: 1, page_size: 200, items: xs })
  await renderComposer('/new', { routes: { 'GET /api/v1/transactions': page(items(30, 19)) } })
  expect(await screen.findByRole('button', { name: 'Currency: EUR. Change' })).toBeInTheDocument()
})

it('the 21st entry back being foreign does not bring the currency back', async () => {
  const xs = Array.from({ length: 30 }, (_, i) => ({ ...TXN, id: `t${i}`, currency: i === 20 ? 'USD' : 'EUR' }))
  await renderComposer('/new', { routes: { 'GET /api/v1/transactions': { total: 30, page: 1, page_size: 200, items: xs } } })
  await ready()
  expect(screen.queryByRole('button', { name: 'Currency: EUR. Change' })).not.toBeInTheDocument()
})

it('editing a foreign entry keeps the currency on the form', async () => {
  await renderComposer('/edit/t9', { routes: { 'GET /api/v1/transactions/t9': { ...TXN, currency: 'GBP', exchange_rate: 1.15 } } })
  await ready()
  expect(screen.getByRole('button', { name: 'Currency: GBP. Change' })).toBeInTheDocument()
})

// Fix round 1, finding 12: the edited entry's own currency is what keeps the chip on the form after it is switched back.
it('an edited foreign entry switched to the household currency keeps the currency on the form', async () => {
  await renderComposer('/edit/t9', { routes: { 'GET /api/v1/transactions/t9': { ...TXN, currency: 'GBP', exchange_rate: 1.15 } } })
  await ready()
  fireEvent.click(screen.getByRole('button', { name: 'Currency: GBP. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'EUR · euro' }))
  expect(await screen.findByRole('button', { name: 'Currency: EUR. Change' })).toBeInTheDocument()
})

// Finding 8: the currency picked from More returns to More, where the rate is.
it('picking the currency from More goes back to More', async () => {
  await renderComposer('/new')
  await ready()
  fireEvent.click(screen.getByRole('button', { name: 'More options' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'More' })).getByRole('button', { name: 'Currency: EUR. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'GBP · pounds' }))
  const more = await screen.findByRole('dialog', { name: 'More' })
  expect(within(more).getByLabelText('Rate')).toBeInTheDocument()
})
