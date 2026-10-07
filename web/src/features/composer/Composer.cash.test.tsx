import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { keys } from '../../data/keys'
import { resetTestEnv, testQueryClient } from '../../test/render'
import { renderComposer, TXN } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

// Plan › Cash §4.7: a composer save or delete of a cash expense makes the cash reads stale.
const CASH = [keys.cashWallets('2026-10'), keys.cashMovements('2026-10'), keys.cashStash()]
function seeded() {
  const client = testQueryClient()
  for (const k of CASH) client.setQueryData(k, { seeded: true })
  return client
}
const stale = (client: ReturnType<typeof testQueryClient>) => CASH.map((k) => client.getQueryState(k)?.isInvalidated)

it('a cash save invalidates cashWallets, cashMovements and cashStash', async () => {
  const client = seeded()
  await renderComposer('/new?mode=cash&take=none&amount=12', { client })
  fireEvent.click(await screen.findByRole('button', { name: /^Save 12 euro/ }))
  await screen.findByText('home screen')
  await waitFor(() => expect(stale(client)).toEqual([true, true, true]))
})

it('a card save leaves the cash reads alone', async () => {
  const client = seeded()
  await renderComposer('/new?amount=3', { client })
  fireEvent.click(await screen.findByRole('button', { name: 'Save 3 euro to Day to day' }))
  await screen.findByText('home screen')
  expect(stale(client)).toEqual([false, false, false])
})

it('deleting a cash expense invalidates the cash reads', async () => {
  const client = seeded()
  await renderComposer('/edit/t9', {
    client,
    routes: { 'GET /api/v1/transactions/t9': { ...TXN, payment_method: 'cash', paid_by: 'u1' }, 'DELETE /api/v1/transactions/t9': () => null },
  })
  fireEvent.click(await screen.findByRole('button', { name: 'More actions' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Entry' })).getByRole('button', { name: 'Delete' }))
  const ask = await screen.findByRole('dialog', { name: 'Delete this entry?' })
  fireEvent.click(within(ask).getByRole('button', { name: 'Delete' }))
  await screen.findByText('home screen')
  await waitFor(() => expect(stale(client)).toEqual([true, true, true]))
})
