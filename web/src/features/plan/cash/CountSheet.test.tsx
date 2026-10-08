import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { cashRoutes, cashWallets, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { Cash } from './Cash'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

// Polish C5: every cash write carries the sheet's client_id (a uuid4).
const anId = expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)

const posts = (api: ReturnType<typeof fakeApi>) =>
  api.calls.filter((c) => c.method === 'POST' && c.path === '/api/v1/cash/movements')

it('Count now opens the count; the preview shows book → counted · correction; the body is the counted amount', async () => {
  const api = fakeApi({ ...readRoutes(), ...cashRoutes({ wallets: cashWallets({ stash: -20 }) }) })
  renderWithProviders(<Cash />)
  fireEvent.click(await screen.findByRole('button', { name: 'Count now' }))
  const sheet = await screen.findByRole('dialog', { name: 'Count your stash' })
  expect(sheet).toHaveTextContent('How much is in your stash right now?')
  expect(within(sheet).getByLabelText('Counted')).toHaveFocus()
  fireEvent.change(within(sheet).getByLabelText('Counted'), { target: { value: '0' } })
  expect(within(sheet).getByTestId('count-preview')).toHaveTextContent('By the book −€20.00 → Counted €0.00 · correction +€20.00')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save count' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({ client_id: anId, kind: 'stash_count', amount: '0.00' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('Count from the stash card: a lower count is a negative correction; a comma decimal parses', async () => {
  const api = fakeApi({ ...readRoutes(), ...cashRoutes() })
  renderWithProviders(<Cash />)
  const stash = await screen.findByRole('region', { name: 'My stash' })
  fireEvent.click(within(stash).getByRole('button', { name: 'Count' }))
  const sheet = await screen.findByRole('dialog', { name: 'Count your stash' })
  expect(within(sheet).getByRole('button', { name: 'Save count' })).toBeDisabled()
  fireEvent.change(within(sheet).getByLabelText('Counted'), { target: { value: '359,5' } })
  expect(within(sheet).getByTestId('count-preview')).toHaveTextContent('By the book €380.00 → Counted €359.50 · correction −€20.50')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save count' }))
  await waitFor(() => expect(posts(api)).toHaveLength(1))
  expect(posts(api)[0].body).toEqual({ client_id: anId, kind: 'stash_count', amount: '359.50' })
})

it('a count that matches says so, and can still be saved', async () => {
  fakeApi({ ...readRoutes(), ...cashRoutes() })
  renderWithProviders(<Cash />)
  const stash = await screen.findByRole('region', { name: 'My stash' })
  fireEvent.click(within(stash).getByRole('button', { name: 'Count' }))
  const sheet = await screen.findByRole('dialog', { name: 'Count your stash' })
  fireEvent.change(within(sheet).getByLabelText('Counted'), { target: { value: '380' } })
  expect(within(sheet).getByTestId('count-preview')).toHaveTextContent('correction €0.00')
  expect(within(sheet).getByRole('button', { name: 'Save count' })).toBeEnabled()
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('Save count disables live when the device goes offline', async () => {
  fakeApi({ ...readRoutes(), ...cashRoutes() })
  renderWithProviders(<Cash />)
  const stash = await screen.findByRole('region', { name: 'My stash' })
  fireEvent.click(within(stash).getByRole('button', { name: 'Count' }))
  const sheet = await screen.findByRole('dialog', { name: 'Count your stash' })
  fireEvent.change(within(sheet).getByLabelText('Counted'), { target: { value: '10' } })
  expect(within(sheet).getByRole('button', { name: 'Save count' })).toBeEnabled()
  act(() => setOnline(false))
  expect(within(sheet).getByRole('button', { name: 'Save count' })).toBeDisabled()
  expect(within(sheet).getByText('Connect to change cash')).toBeInTheDocument()
})
