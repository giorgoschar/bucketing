import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { todayLocal } from './dates'
import { writes } from './testHelpers'
import { renderComposer, TXN } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

it('edit: loads the stored values, locks the type, sends a full PUT with the stored settlement flag', async () => {
  const { api } = await renderComposer('/edit/t9', { routes: { 'GET /api/v1/transactions/t9': TXN, 'PUT /api/v1/transactions/t9': TXN } })
  expect(await screen.findByText('Amount 64.20 euro')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Income' })).toBeDisabled() // 2a's Segmented: aria-pressed buttons
  expect(screen.queryByRole('button', { name: 'Cash from wallet' })).not.toBeInTheDocument()
  expect(screen.getByPlaceholderText('Where? (optional)')).toHaveValue('Taverna')
  fireEvent.click(screen.getByRole('button', { name: 'Delete last digit' }))
  fireEvent.click(screen.getByRole('button', { name: '5' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  const [put] = writes(api)
  expect(put).toMatchObject({ method: 'PUT', path: '/api/v1/transactions/t9' })
  expect(put.body).toMatchObject({
    amount: '64.25', exclude_from_settlement: true, payer_mode: 'single', paid_by: 'u2', bucket_id: 'b-day', transaction_date: '2026-10-01',
  })
  expect(put.body).not.toHaveProperty('client_id')
  expect(api.calls.some((c) => c.path.endsWith('/check-duplicate'))).toBe(false)
  expect(await screen.findByText('Saved changes')).toBeInTheDocument()
})

it('an archived budget keeps its name and its id (Review Focus 3)', async () => {
  const { api } = await renderComposer('/edit/t9', {
    routes: { 'GET /api/v1/transactions/t9': { ...TXN, bucket_id: 'b-old' }, 'PUT /api/v1/transactions/t9': TXN },
  })
  expect(await screen.findByRole('button', { name: 'Budget: Old budget. Change' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ bucket_id: 'b-old' })
})

it('a Fixed cost shows a read-only budget and keeps bucket_id null', async () => {
  const { api } = await renderComposer('/edit/t9', {
    routes: { 'GET /api/v1/transactions/t9': { ...TXN, bucket_id: null, recurring_bill_id: 'r1' }, 'PUT /api/v1/transactions/t9': TXN },
  })
  expect(await screen.findByLabelText('Budget: Fixed cost')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ bucket_id: null })
})

it('Delete asks first, sends DELETE and closes; a 404 counts as done', async () => {
  const { api } = await renderComposer('/edit/t9', {
    routes: {
      'GET /api/v1/transactions/t9': TXN,
      'DELETE /api/v1/transactions/t9': () => Response.json({ detail: 'Transaction not found' }, { status: 404 }),
    },
  })
  fireEvent.click(await screen.findByRole('button', { name: 'More actions' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Entry' })).getByRole('button', { name: 'Delete' }))
  const ask = await screen.findByRole('dialog', { name: 'Delete this entry?' })
  fireEvent.click(within(ask).getByRole('button', { name: 'Delete' }))
  await screen.findByText('home screen')
  expect(writes(api)).toEqual([expect.objectContaining({ method: 'DELETE', path: '/api/v1/transactions/t9' })])
})

it('a missing entry says so, with Back', async () => {
  await renderComposer('/edit/t404', {
    routes: { 'GET /api/v1/transactions/t404': () => Response.json({ detail: 'Transaction not found' }, { status: 404 }) },
  })
  expect(await screen.findByText('This entry no longer exists')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  await screen.findByText('home screen')
})

it('offline with nothing cached: "Connect once to load this entry."', async () => {
  await renderComposer('/edit/t9', {
    routes: { 'GET /api/v1/transactions/t9': () => Promise.reject(new TypeError('Failed to fetch')) },
  })
  expect(await screen.findByText('Connect once to load this entry.')).toBeInTheDocument()
})

it('/new?from= copies an entry as a new one dated today with a fresh client_id', async () => {
  const { api } = await renderComposer('/new?from=t9', { routes: { 'GET /api/v1/transactions/t9': TXN } })
  expect(await screen.findByText('Amount 64.20 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save 64 euro 20 to Day to day' }))
  await screen.findByText('home screen')
  expect(writes(api)[0]).toMatchObject({
    method: 'POST',
    body: { amount: '64.20', merchant: 'Taverna', transaction_date: todayLocal(), client_id: expect.stringMatching(/^[0-9a-f-]{36}$/) },
  })
})
