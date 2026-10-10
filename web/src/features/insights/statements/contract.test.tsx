import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import listPayload from './__fixtures__/statements-list.json'
import statementPayload from './__fixtures__/statement-reviewed-2026-09.json'
import { StatementView } from './Statement'
import { StatementsList } from './StatementsList'
import type { StatementListOut, StatementOut } from './types'

// The two payloads are the unedited answers of the real server (tests/test_phase_b_statement.py's seeded September,
// reviewed by its household's user, read with GET /insights/statements/2026-09 and GET /insights/statements).
// They guard the contract: a server that sends reviewed_at without reviewed_on would show "Closed automatically".
const statement = statementPayload as StatementOut
const list = listPayload as StatementListOut

vi.mock('../../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'someone-else', household_id: 'h1', display_name: 'Maria' }, signOut: vi.fn() }),
}))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 10, 12))
})
afterEach(resetTestEnv)

const section = async (name: string) => within(await screen.findByRole('region', { name }))

it('the real reviewed statement: the reviewed line, and one row of every section', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/insights/statements/{month}': () => statement })
  renderWithProviders(<StatementView month="2026-09" />, { route: '/insights/statements/2026-09' })
  expect(await screen.findByText('Reviewed on 10 October by User1')).toBeInTheDocument()
  expect(screen.queryByText('Closed automatically')).toBeNull()

  expect((await section('In, out and net')).getByText('Same as August')).toBeInTheDocument()
  expect((await section('Planned vs actual')).getByText('Gym')).toBeInTheDocument()
  expect((await section('Budgets that ran over')).getByText('Daily')).toBeInTheDocument()
  expect((await section('Bills that changed')).getByRole('link', { name: /Electricity was €84, usually €61/ })).toBeInTheDocument()
  expect((await section('Cash not logged')).getByText('User1')).toBeInTheDocument()
  const cat = (await section('Categories above usual')).getByRole('link', { name: /Eating out/ })
  expect(cat).toHaveAttribute('href', expect.stringContaining(`/insights/category/${statement.categories_over[0].category_id}`))
  expect((await section('Biggest expenses')).getByText('IKEA')).toBeInTheDocument()
})

it('the real list: September carries the Reviewed mark, the closed months none', async () => {
  fakeApi({ 'GET /api/v1/insights/statements': () => list })
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  expect(await screen.findByRole('link', { name: /September 2026/ })).toHaveTextContent('Reviewed')
  expect(screen.getByRole('link', { name: /August 2026/ })).not.toHaveTextContent(/Reviewed|Open for review/)
  expect(screen.getByRole('link', { name: /June 2026/ })).toHaveAttribute('href', '/insights/statements/2026-06')
})
