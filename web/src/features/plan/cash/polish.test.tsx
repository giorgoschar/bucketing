import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { type FakeApi, fakeApi, reply } from '../../../test/fakeApi'
import { cashRoutes, cashWallets, readRoutes, wallet, walletMember } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import { Cash } from './Cash'
import type { WalletWithTerms } from './contractTypes'
import { CENT_EPS, walletSum } from './format'
import type { WalletOut } from './types'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

/** Polish P3: the cash client_id (C5) and the wallet's full sum (C6). */

const MOVEMENTS = 'POST /api/v1/cash/movements' as const
const posts = (api: FakeApi) => api.callsTo(MOVEMENTS)
const idOf = (api: FakeApi, n: number) => (posts(api)[n].body as { client_id: string }).client_id
const terms = (over: Partial<WalletWithTerms>): WalletOut => wallet(over as Partial<WalletOut>)

async function renderCash(over: Parameters<typeof cashRoutes>[0] = {}) {
  const api = fakeApi({ ...readRoutes(), ...cashRoutes(over) })
  renderWithProviders(<Cash />, { route: '/plan?view=cash' })
  return api
}
const card = () => screen.findByRole('article', { name: "Giorgos's wallet" })

// ---- C5: one client_id per write

it('a take that fails is retried with the same client_id; the next take gets a new one', async () => {
  const api = await renderCash()
  api.on(MOVEMENTS, () => reply(502))
  const stash = await screen.findByRole('region', { name: 'My stash' })
  fireEvent.click(within(stash).getByRole('button', { name: 'Take' }))
  const sheet = await screen.findByRole('dialog', { name: 'Take cash' })
  fireEvent.change(within(sheet).getByLabelText('Amount'), { target: { value: '40' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €40.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  // The sheet stays open on the failure: the retry is the same write.
  await waitFor(() => expect(within(sheet).getByRole('button', { name: 'Take €40.00' })).toBeEnabled())
  api.on(MOVEMENTS, () => Response.json({ id: 'm-new' }, { status: 201 }))
  fireEvent.click(within(sheet).getByRole('button', { name: 'Take €40.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(2))
  expect(idOf(api, 1)).toBe(idOf(api, 0))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

  fireEvent.click(within(await screen.findByRole('region', { name: 'My stash' })).getByRole('button', { name: 'Take' }))
  const again = await screen.findByRole('dialog', { name: 'Take cash' })
  fireEvent.change(within(again).getByLabelText('Amount'), { target: { value: '40' } })
  fireEvent.click(within(again).getByRole('button', { name: 'Take €40.00' }))
  await waitFor(() => expect(posts(api)).toHaveLength(3))
  expect(idOf(api, 2)).not.toBe(idOf(api, 0))
})

it('a count that fails is retried with the same client_id', async () => {
  const api = await renderCash({ wallets: cashWallets({ stash: -20 }) })
  api.on(MOVEMENTS, () => reply(503))
  fireEvent.click(await screen.findByRole('button', { name: 'Count now' }))
  const sheet = await screen.findByRole('dialog', { name: 'Count your stash' })
  fireEvent.change(within(sheet).getByLabelText('Counted'), { target: { value: '0' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save count' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  await waitFor(() => expect(within(sheet).getByRole('button', { name: 'Save count' })).toBeEnabled())
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save count' }))
  await waitFor(() => expect(posts(api)).toHaveLength(2))
  expect(idOf(api, 1)).toBe(idOf(api, 0))
})

// ---- C6: the wallet's full sum

it('cash of this month logged in another month: "− Logged in another month", and the sum adds up', async () => {
  // Took 100 on 28 Sep, logged 60 in September and 40 in October (Cash final review m2, scenario A).
  const me = walletMember({ wallet: terms({ taken: 100, logged: 60, logged_cross_month: 40, not_yet_logged: 0 }) })
  await renderCash({ wallets: cashWallets({ members: [me] }) })
  const c = await card()
  expect(c).toHaveTextContent('Took €100.00 − Logged €60.00 − Logged in another month €40.00')
  expect(within(c).getByText('− Logged in another month')).toBeVisible()
  expect(c).toHaveTextContent('All logged')
})

it('logged beyond what was in hand: "+ Logged more than taken", and the sum adds up', async () => {
  // Took 100, said Still have 50, then logged 70 after it (scenario B): 20 came from cash never recorded.
  const me = walletMember({ wallet: terms({ taken: 100, still_have: 0, logged: 70, over_logged: 20, not_yet_logged: 50 }) })
  await renderCash({ wallets: cashWallets({ members: [me] }) })
  const c = await card()
  expect(c).toHaveTextContent(
    'Took €100.00 − In hand €0.00 − Logged €70.00 + Logged more than taken €20.00 = €50.00 not yet logged')
  expect(within(c).getByText('+ Logged more than taken')).toBeVisible()
})

it('no extra lines when both terms are zero', async () => {
  const me = walletMember({ wallet: terms({ logged_cross_month: 0, over_logged: 0.004 }) })
  await renderCash({ wallets: cashWallets({ members: [me] }) })
  const c = await card()
  expect(c).toHaveTextContent('Took €120.00 − Logged €75.00 = €45.00 not yet logged')
  expect(c.querySelector('.cash-terms')).toBeNull()
})

it('your own Took never shows below zero (Cash final review m3)', async () => {
  // Took 100 in September, put 20 back in October with no takes: October's taken − put back is −20.
  const me = walletMember({ wallet: terms({ taken: 0, put_back: 20, logged: 0, spent: 0, over_logged: 0, not_yet_logged: 0 }) })
  await renderCash({ wallets: cashWallets({ members: [me] }) })
  const c = await card()
  expect(c).toHaveTextContent('Took €0.00 − Logged €0.00')
  expect(c).not.toHaveTextContent('−€')
  expect(c.querySelector('.cash-terms')).toBeNull()
})

// Fix round 1 (review C-1): the server's over_logged is already against the floored Took (stream S
// `_over_logged`), so the card adds it as it comes.
it('put back beyond the takes, then logged: "+ Logged more than taken" as the server sends it, and the sum adds up', async () => {
  // October: no takes, €20 put back, €15 logged. S: Took max(0 − 20, 0) = 0, over_logged = 0 − (0 − 15) = 15.
  const me = walletMember({ wallet: terms({ taken: 0, put_back: 20, logged: 15, spent: 0, over_logged: 15, not_yet_logged: 0 }) })
  await renderCash({ wallets: cashWallets({ members: [me] }) })
  const c = await card()
  expect(c).toHaveTextContent('Took €0.00 − Logged €15.00 + Logged more than taken €15.00')
  expect(within(c).getByText('+ Logged more than taken')).toBeInTheDocument()
  expect(c).toHaveTextContent('All logged')
})

it.each<[string, Partial<WalletWithTerms>]>([
  ['plain', { carried: 10, taken: 130, put_back: 20, still_have: 15, logged: 70, outs: 5, not_yet_logged: 30 }],
  ['cross-month', { taken: 100, logged: 60, logged_cross_month: 40, not_yet_logged: 0 }],
  ['excess', { taken: 100, still_have: 0, logged: 70, over_logged: 20, not_yet_logged: 50 }],
  ['both', { carried: 5, taken: 80, logged: 30, outs: 5, logged_cross_month: 25, over_logged: 10, not_yet_logged: 35 }],
  ['put back beyond takes', { taken: 0, put_back: 20, logged: 0, over_logged: 0, not_yet_logged: 0 }],
  ['put back beyond takes, then logged', { taken: 0, put_back: 20, logged: 15, over_logged: 15, not_yet_logged: 0 }],
])('the shown sum equals not_yet_logged: %s', (_name, w) => {
  const s = walletSum(walletMember({ wallet: terms({ carried: 0, put_back: 0, still_have: null, outs: 0, ...w }) }))
  const shown = s.took - (s.inHand ?? 0) - s.logged - s.crossMonth + s.overLogged
  expect(Math.abs(shown - s.notLogged)).toBeLessThan(CENT_EPS)
  expect(s.took).toBeGreaterThanOrEqual(0)
})
