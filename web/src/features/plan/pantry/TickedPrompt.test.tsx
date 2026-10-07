import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TXN, created, renderComposer } from '../../composer/testing'
import { goOffline } from '../../composer/testHelpers'
import { hang, reply } from '../../../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../../../test/render'
import { resetTickedPrompt } from './tickedOffer'
import { TickedPrompt } from './TickedPrompt'

vi.mock('../../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(async () => {
  resetTickedPrompt()
  await resetTestEnv()
})

const SUMMARY = 'GET /api/v1/stock/summary'
const APPLY = 'POST /api/v1/stock/shopping/apply-ticked'
const summary = (ticked: number) => ({ [SUMMARY]: { low_count: 3, ticked_count: ticked } })
const applied = { applied: [{ name: 'Milk', before: 0, after: 2 }, { name: 'Olive oil', before: 1, after: 2 }], cleared_lines: 0 }

/** The composer, plus the prompt host that AppShell mounts (it outlives the composer). */
async function compose(url = '/new', routes: Record<string, unknown> = {}) {
  const client = testQueryClient()
  const out = await renderComposer(url, { routes: { [APPLY]: applied, ...routes }, client })
  render(<QueryClientProvider client={client}><TickedPrompt /></QueryClientProvider>)
  return out
}
const ready = () => screen.findByRole('button', { name: 'Budget: Day to day. Change' })
const saveThree = async () => {
  await ready()
  fireEvent.click(screen.getByRole('button', { name: '3' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save 3 euro to Day to day' }))
  await screen.findByText('home screen')
}

it('after a new expense saves with ticked items, it offers to add them to the pantry', async () => {
  const { api } = await compose('/new', summary(2))
  await saveThree()
  const sheet = await screen.findByRole('dialog', { name: '2 ticked pantry items' })
  expect(sheet).toHaveTextContent('Add them to the pantry?')
  expect(api.callsTo(SUMMARY)).toHaveLength(1)
  expect(api.callsTo(APPLY)).toHaveLength(0)
  // The save's own toast is still there: the prompt never replaces it.
  expect(screen.getByText('Saved €3.00 to Day to day')).toBeInTheDocument()
})

it('Add to pantry calls apply-ticked and toasts what went in', async () => {
  const { api } = await compose('/new', summary(2))
  await saveThree()
  const sheet = await screen.findByRole('dialog', { name: '2 ticked pantry items' })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add to pantry' }))
  expect(await screen.findByText('Milk 0 → 2 · Olive oil 1 → 2')).toBeInTheDocument()
  expect(api.callsTo(APPLY)).toHaveLength(1)
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('Not now dismisses it without touching the pantry', async () => {
  const { api } = await compose('/new', summary(1))
  await saveThree()
  const sheet = await screen.findByRole('dialog', { name: '1 ticked pantry item' })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Not now' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(api.callsTo(APPLY)).toHaveLength(0)
})

it('nothing ticked: no prompt', async () => {
  const { api } = await compose('/new', summary(0))
  await saveThree()
  await waitFor(() => expect(api.callsTo(SUMMARY)).toHaveLength(1))
  await act(() => new Promise((r) => setTimeout(r, 20)))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('a failed summary call: no prompt, and the save is unaffected', async () => {
  const { api } = await compose('/new', { [SUMMARY]: () => reply(500, { detail: 'boom' }) })
  await saveThree()
  await waitFor(() => expect(api.callsTo(SUMMARY)).toHaveLength(1))
  await act(() => new Promise((r) => setTimeout(r, 20)))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByText('Saved €3.00 to Day to day')).toBeInTheDocument()
})

it('never delays the save: a summary that never answers still leaves the composer at once', async () => {
  const { api } = await compose('/new', { [SUMMARY]: () => hang() })
  await saveThree()
  expect(screen.getByText('Saved €3.00 to Day to day')).toBeInTheDocument()
  await waitFor(() => expect(api.callsTo(SUMMARY)).toHaveLength(1))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('a failed save asks nothing', async () => {
  const { api } = await compose('/new', { ...summary(2), 'POST /api/v1/transactions': () => reply(400, { detail: 'Nope.' }) })
  await ready()
  fireEvent.click(screen.getByRole('button', { name: '3' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save 3 euro to Day to day' }))
  expect(await screen.findByText('Nope.')).toBeInTheDocument()
  expect(api.callsTo(SUMMARY)).toHaveLength(0)
})

it('an edit: no prompt', async () => {
  const { api } = await compose('/edit/t9', { ...summary(2), 'GET /api/v1/transactions/t9': TXN, 'PUT /api/v1/transactions/t9': TXN })
  expect(await screen.findByText('Amount 64.20 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Delete last digit' }))
  fireEvent.click(screen.getByRole('button', { name: '5' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  await act(() => new Promise((r) => setTimeout(r, 20)))
  expect(api.callsTo(SUMMARY)).toHaveLength(0)
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('income: no prompt', async () => {
  const { api } = await compose('/new', { ...summary(2), 'POST /api/v1/transactions': () => created({ type: 'income' }) })
  await ready()
  fireEvent.click(screen.getByRole('button', { name: 'Income' }))
  fireEvent.click(screen.getByRole('button', { name: '7' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save income 7 euro' }))
  await screen.findByText('home screen')
  await act(() => new Promise((r) => setTimeout(r, 20)))
  expect(api.callsTo(SUMMARY)).toHaveLength(0)
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('offline (the save is queued): no prompt', async () => {
  await compose('/new', summary(2))
  await ready()
  goOffline()
  fireEvent.click(screen.getByRole('button', { name: '3' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save 3 euro to Day to day' }))
  await screen.findByText('home screen')
  expect(await screen.findByText("Saved on this phone. It will sync when you're back online.")).toBeInTheDocument()
  await act(() => new Promise((r) => setTimeout(r, 20)))
  const fetches = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input instanceof Request ? input.url : input))
  expect(fetches.some((u) => u.includes('/stock/summary'))).toBe(false)
  expect(screen.queryByRole('dialog')).toBeNull()
})
