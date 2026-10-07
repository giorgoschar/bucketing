import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { writes } from './testHelpers'
import { renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))
vi.mock('./defaults', async (importOriginal) => ({ ...(await importOriginal<typeof import('./defaults')>()), RULES_API_READY: true }))
const cam = vi.hoisted(() => ({ decode: null as null | ((t: string) => void) }))
vi.mock('./scan/qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./scan/qr')>()),
  startQr: vi.fn(async (_v: HTMLVideoElement, onDecode: (t: string) => void) => {
    cam.decode = onDecode
    return { stop: () => {} }
  }),
}))

afterEach(resetTestEnv)

it('changing the scanned category offers Remember, on by default; Save sends one rule POST', async () => {
  const { api } = await renderComposer('/new', {
    routes: {
      'GET /api/v1/settings/category-rules': [],
      'POST /api/v1/transactions/scan/qr': { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' },
      'POST /api/v1/settings/category-rules': () => Response.json({ id: 'r1', pattern: 'test taverna', category_id: 'c-coffee' }, { status: 201 }),
    },
  })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!('https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc'))
  await screen.findByText('Read from myDATA QR')
  expect(screen.queryByRole('switch', { name: /^Remember/ })).not.toBeInTheDocument() // same as the server's suggestion
  fireEvent.click(screen.getByRole('button', { name: 'Category: Eating out, from receipt. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Coffee/ }))
  expect(screen.getByRole('switch', { name: 'Remember "Test Taverna" → "Coffee"' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(screen.getByRole('button', { name: /^Save 12 euro 50/ }))
  await screen.findByText('home screen')
  const rules = writes(api).filter((c) => c.path === '/api/v1/settings/category-rules')
  expect(rules).toEqual([expect.objectContaining({ body: { pattern: 'Test Taverna', category_id: 'c-coffee' } })])
})
