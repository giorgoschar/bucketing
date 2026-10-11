import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { reply } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { goOffline, writes } from '../composer/testHelpers'
import { renderComposer, TXN } from '../composer/testing'
import { dismissToast } from '../../ui/Toast'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(async () => {
  dismissToast()
  await resetTestEnv()
})

// Phase C spec §3.2 (the prompt) and §3.4 (the composer uses rules).
const SUGGESTION = { pattern: 'lidl', label: 'Lidl', category_id: 'c-food', category_name: 'Groceries' }
const SUGGEST = 'GET /api/v1/category-rules/suggestion'
const RULE = '/api/v1/settings/category-rules'
const ruleRoutes = (suggest: unknown = SUGGESTION) => ({
  [SUGGEST]: suggest,
  'POST /api/v1/settings/category-rules': () => ({ id: 'r1', pattern: 'lidl', category_id: 'c-food' }),
  'POST /api/v1/category-rules/suggestion/dismiss': () => ({ ok: true }),
})
const press = (d: string) => fireEvent.click(screen.getByRole('button', { name: d }))
const askedFor = (api: { calls: { path: string; query: URLSearchParams }[] }) => api.calls.filter((c) => c.path === '/api/v1/category-rules/suggestion')

async function saveOne(extra: Record<string, unknown> = {}) {
  const r = await renderComposer('/new', { routes: { ...ruleRoutes(), ...extra } })
  await screen.findByRole('button', { name: /^Budget: Day to day/ })
  press('5')
  fireEvent.click(screen.getByRole('button', { name: /^Save 5 euro/ }))
  await screen.findByText('home screen')
  return r
}

it('after a save, the server is asked about the new entry and the toast offers the rule', async () => {
  const { api } = await saveOne()
  expect(await screen.findByText('Always use Groceries for Lidl?')).toBeInTheDocument()
  expect(askedFor(api)).toHaveLength(1)
  expect(askedFor(api)[0].query.get('transaction_id')).toBe('t1')
  const region = within(screen.getByRole('status'))
  expect(region.getByRole('button', { name: 'Always' })).toBeInTheDocument()
  expect(region.getByRole('button', { name: 'Not now' })).toBeInTheDocument()
})

it('Always creates the rule with the pattern and category, then says where to change it', async () => {
  const { api } = await saveOne()
  fireEvent.click(await screen.findByRole('button', { name: 'Always' }))
  expect(await screen.findByText('Rule saved. Change it in Settings › Categories.')).toBeInTheDocument()
  const rule = writes(api).filter((c) => c.path === RULE)
  expect(rule).toHaveLength(1)
  expect(rule[0].body).toEqual({ pattern: 'lidl', category_id: 'c-food' })
  expect(writes(api).some((c) => c.path.endsWith('/dismiss'))).toBe(false)
})

it('Not now sends the dismissal with the pattern and creates no rule', async () => {
  const { api } = await saveOne()
  fireEvent.click(await screen.findByRole('button', { name: 'Not now' }))
  await waitFor(() => expect(writes(api).some((c) => c.path === '/api/v1/category-rules/suggestion/dismiss')).toBe(true))
  expect(writes(api).find((c) => c.path.endsWith('/dismiss'))!.body).toEqual({ pattern: 'lidl' })
  expect(writes(api).some((c) => c.path === RULE)).toBe(false)
  expect(screen.queryByText('Always use Groceries for Lidl?')).not.toBeInTheDocument()
})

it('a failed Always says so and does not claim the rule is saved', async () => {
  await saveOne({ 'POST /api/v1/settings/category-rules': () => reply(500, { detail: 'Boom' }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Always' }))
  expect(await screen.findByText('Boom')).toBeInTheDocument()
  expect(screen.queryByText(/Rule saved/)).not.toBeInTheDocument()
})

it('ignoring the prompt sends nothing', async () => {
  const { api } = await saveOne()
  await screen.findByText('Always use Groceries for Lidl?')
  dismissToast()
  expect(writes(api).filter((c) => c.path !== '/api/v1/transactions')).toHaveLength(0)
})

it('nothing is shown when the server answers null', async () => {
  const { api } = await saveOne({ [SUGGEST]: null })
  await waitFor(() => expect(askedFor(api)).toHaveLength(1))
  await new Promise((r) => setTimeout(r, 30))
  expect(screen.queryByText(/Always use/)).not.toBeInTheDocument()
  expect(screen.getByText(/^Saved/)).toBeInTheDocument()
})

it('nothing is shown, and no error, when the suggestion request fails', async () => {
  const { api } = await saveOne({ [SUGGEST]: () => reply(500, { detail: 'down' }) })
  await waitFor(() => expect(askedFor(api)).toHaveLength(1))
  await new Promise((r) => setTimeout(r, 30))
  expect(screen.queryByText(/Always use/)).not.toBeInTheDocument()
  expect(screen.queryByText('down')).not.toBeInTheDocument()
})

it('offline, the entry is queued and no suggestion is asked for', async () => {
  const { api } = await renderComposer('/new', { routes: ruleRoutes() })
  await screen.findByRole('button', { name: /^Budget: Day to day/ })
  goOffline()
  press('5')
  fireEvent.click(screen.getByRole('button', { name: /^Save 5 euro/ }))
  await screen.findByText('home screen')
  await new Promise((r) => setTimeout(r, 30))
  expect(askedFor(api)).toHaveLength(0)
  expect(screen.queryByText(/Always use/)).not.toBeInTheDocument()
})

it('editing without changing the category asks nothing; changing it asks', async () => {
  const routes = {
    ...ruleRoutes(),
    'GET /api/v1/transactions/t9': TXN,
    'PUT /api/v1/transactions/t9': () => ({ ...TXN, category_id: 'c-food' }),
  }
  const same = await renderComposer('/edit/t9', { routes })
  fireEvent.click(await screen.findByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  await new Promise((r) => setTimeout(r, 30))
  expect(askedFor(same.api)).toHaveLength(0)
})

it('editing with another category asks about that entry', async () => {
  const routes = {
    ...ruleRoutes(),
    'GET /api/v1/transactions/t9': TXN,
    'PUT /api/v1/transactions/t9': () => ({ ...TXN, category_id: 'c-food' }),
  }
  const { api } = await renderComposer('/edit/t9', { routes })
  fireEvent.click(await screen.findByRole('button', { name: /^Category:/ }))
  fireEvent.click(await screen.findByRole('button', { name: /^Groceries/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  expect(await screen.findByText('Always use Groceries for Lidl?')).toBeInTheDocument()
  expect(askedFor(api)[0].query.get('transaction_id')).toBe('t9')
})

// §3.4
const rules = { 'GET /api/v1/settings/category-rules': [{ id: 'r1', pattern: 'lidl', category_id: 'c-food' }] }
const merchant = () => screen.getByPlaceholderText('Where? (optional)')

it.each(['LIDL Express', 'lidl ', 'LÍDL Athens'])('typing "%s" pre-selects the rule\'s category', async (text) => {
  await renderComposer('/new', { routes: rules })
  await screen.findByRole('button', { name: /^Budget:/ })
  fireEvent.change(merchant(), { target: { value: text } })
  expect(await screen.findByRole('button', { name: /^Category: Groceries, rule: lidl/ })).toBeInTheDocument()
})

it('a Greek merchant matches a rule typed in another case', async () => {
  await renderComposer('/new', { routes: { 'GET /api/v1/settings/category-rules': [{ id: 'r2', pattern: 'ΛΙΝΤΛ', category_id: 'c-food' }] } })
  await screen.findByRole('button', { name: /^Budget:/ })
  fireEvent.change(merchant(), { target: { value: 'Λιντλ Αθήνα' } })
  expect(await screen.findByRole('button', { name: /^Category: Groceries/ })).toBeInTheDocument()
})

it('a category the user picked is never overwritten by a rule', async () => {
  await renderComposer('/new', { routes: rules })
  await screen.findByRole('button', { name: /^Budget:/ })
  fireEvent.click(screen.getByRole('button', { name: /^Category:/ }))
  fireEvent.click(await screen.findByRole('button', { name: /^Eating out/ }))
  fireEvent.change(merchant(), { target: { value: 'Lidl' } })
  expect(screen.getByRole('button', { name: /^Category: Eating out/ })).toBeInTheDocument()
})
