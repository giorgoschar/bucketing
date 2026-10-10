import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../../../offline/db'
import { fakeApi, reply, type Routes } from '../../../test/fakeApi'
import { entry, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { asRoutes, statement, statementRoutes } from './fixtures'
import { StatementView } from './Statement'
import type { StatementOut } from './types'

vi.mock('../../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'u1', household_id: 'h1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 2, 12))
})
afterEach(resetTestEnv)

const open = (): StatementOut => statement({
  planned: {
    in: { planned: 0, actual: 0 }, out: { planned: 35, actual: 0 },
    open: [
      { entry_id: 'e1', item_id: 'i1', name: 'Gym', direction: 'out', due_date: '2026-09-28', amount: 35, estimated: false, status: 'expected' },
      { entry_id: 'e2', item_id: 'i2', name: 'Water', direction: 'out', due_date: '2026-09-29', amount: 20, estimated: false, status: 'expected' },
    ],
  },
})
const gym = () => entry({ id: 'e1', item_id: 'i1', name: 'Gym', due_date: '2026-09-28', amount: 35 })
const SKIP = 'POST /api/v1/recurring/entries/{entry_id}/skip' as const
const DONE = 'POST /api/v1/recurring/entries/{entry_id}/done' as const
/** The "Still open" rows: buttons named after their entry. */
const rows = () => screen
const statementGets = (fake: ReturnType<typeof fakeApi>) => fake.calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/insights/statements/2026-09')
const render = (extra: Routes = {}) => {
  const fake = fakeApi({ ...readRoutes(), ...statementRoutes(open()), 'GET /api/v1/recurring/entries': () => [gym()], ...extra })
  return { fake, ...renderWithProviders(<StatementView month="2026-09" />, { route: '/insights/statements/2026-09' }) }
}

it('while the entry loads the row is busy, not dead; then the sheet opens', async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => { release = r })
  render({ 'GET /api/v1/recurring/entries': async () => { await gate; return [gym()] } })
  const row = await rows().findByRole('button', { name: /Gym/ })
  fireEvent.click(row)
  await waitFor(() => expect(rows().getByRole('button', { name: /Gym/ })).toHaveAttribute('aria-busy', 'true'))
  expect(rows().getByRole('button', { name: /Gym/ })).toBeDisabled()
  expect(screen.queryByRole('dialog')).toBeNull()
  await act(async () => { release() })
  expect(await screen.findByRole('dialog', { name: 'Gym' })).toBeInTheDocument()
})

it('a failed read says "Couldn’t open this entry." (alert), leaves the row usable, and a second tap tries again', async () => {
  let ok = false
  const { fake } = render({ 'GET /api/v1/recurring/entries': () => (ok ? [gym()] : reply(500)) })
  fireEvent.click(await rows().findByRole('button', { name: /Gym/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t open this entry.')
  expect(rows().getByRole('button', { name: /Gym/ })).toBeEnabled()
  ok = true
  fireEvent.click(rows().getByRole('button', { name: /Gym/ }))
  expect(await screen.findByRole('dialog', { name: 'Gym' })).toBeInTheDocument()
  expect(screen.queryByText('Couldn’t open this entry.')).toBeNull()
  expect(fake.callsTo('GET /api/v1/recurring/entries').length).toBeGreaterThan(1)
})

it('an entry the read does not return (a paused item) gets the same line', async () => {
  render({ 'GET /api/v1/recurring/entries': () => [] })
  fireEvent.click(await rows().findByRole('button', { name: /Gym/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t open this entry.')
  expect(rows().getByRole('button', { name: /Gym/ })).toBeEnabled()
})

it('offline with no saved copy of that day: the same line, no dead tap', async () => {
  const { fake } = render()
  await rows().findByRole('button', { name: /Gym/ })
  setOnline(false)
  fake.down()
  fireEvent.click(rows().getByRole('button', { name: /Gym/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t open this entry.')
  expect(rows().getByRole('button', { name: /Gym/ })).toBeEnabled()
})

it('Skip from the statement: the request, the row leaves "Still open" at once, and the statement is read again', async () => {
  let after = false
  const { fake } = render({
    ...asRoutes({ 'GET /api/v1/insights/statements/2026-09': () => (after ? { ...open(), planned: { ...open().planned, open: open().planned.open.slice(1) } } : open()) }),
    [SKIP]: () => { after = true; return { ...gym(), status: 'skipped' } },
  })
  fireEvent.click(await rows().findByRole('button', { name: /Gym/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Skip' }))
  await waitFor(() => expect(fake.callsTo(SKIP)).toHaveLength(1))
  await waitFor(() => expect(rows().queryByRole('button', { name: /Gym/ })).toBeNull())
  expect(rows().getByRole('button', { name: /Water/ })).toBeInTheDocument()
  await waitFor(() => expect(statementGets(fake).length).toBeGreaterThan(1))
})

it('Pay from the statement: the request carries the entry, the row leaves, the statement is read again', async () => {
  let after = false
  const { fake } = render({
    ...asRoutes({ 'GET /api/v1/insights/statements/2026-09': () => (after ? { ...open(), planned: { ...open().planned, open: open().planned.open.slice(1) } } : open()) }),
    [DONE]: () => { after = true; return { ...gym(), status: 'done' } },
  })
  fireEvent.click(await rows().findByRole('button', { name: /Gym/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Paid' }))
  await waitFor(() => expect(fake.callsTo('GET /api/v1/settings/household').length).toBeGreaterThan(0))
  await new Promise((r) => setTimeout(r, 20))
  fireEvent.click(await screen.findByRole('button', { name: 'Mark paid €35.00' }))
  await waitFor(() => expect(fake.callsTo(DONE)).toHaveLength(1))
  expect(fake.callsTo(DONE)[0].path).toBe('/api/v1/recurring/entries/e1/done')
  await waitFor(() => expect(rows().queryByRole('button', { name: /Gym/ })).toBeNull())
  await waitFor(() => expect(statementGets(fake).length).toBeGreaterThan(1))
})

it('offline: a queued Skip takes the row off the list, so the same entry cannot be queued twice', async () => {
  const { fake } = render()
  fireEvent.click(await rows().findByRole('button', { name: /Gym/ }))
  const skip = await screen.findByRole('button', { name: 'Skip' })
  setOnline(false)
  fireEvent.click(skip)
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  await waitFor(() => expect(rows().queryByRole('button', { name: /Gym/ })).toBeNull())
  expect(fake.callsTo(SKIP)).toHaveLength(0)
  expect(rows().getByRole('button', { name: /Water/ })).toBeInTheDocument()
  expect(await db.queue.count()).toBe(1)
})
