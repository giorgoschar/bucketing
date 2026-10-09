import 'fake-indexeddb/auto'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { db } from '../../offline/db'
import { fakeApi } from '../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { installMemoryStorage } from '../../test/storage'
import { ago, exactTime } from './attemptHooks'
import type { IngestAttempt } from './attemptTypes'
import { RecentAttempts } from './RecentAttempts'

installMemoryStorage()
afterEach(resetTestEnv)

const ATTEMPTS = 'GET /api/v1/ingest/attempts' as const
const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()
const LONG = 'Could not read the amount "twelve euro fifty": send a number such as 12.50 or 12,50, with or without a currency sign, in the Amount field of the Shortcut'
const attempt = (over: Partial<IngestAttempt>): IngestAttempt => ({
  id: 'a1', created_at: minsAgo(5), status_code: 201, outcome: 'created', reason: null, merchant: 'Lidl',
  amount_raw: '€12,50', transaction_id: 't1', token_name: 'iPhone', ...over,
})
const THREE = [
  attempt({}),
  attempt({ id: 'a2', created_at: minsAgo(180), status_code: 200, outcome: 'duplicate', reason: 'Same purchase 1 min earlier', merchant: 'AB', amount_raw: '7.20', transaction_id: 't0' }),
  attempt({ id: 'a3', created_at: minsAgo(60 * 24 * 4), status_code: 422, outcome: 'rejected', reason: LONG, merchant: null, amount_raw: 'twelve euro fifty', transaction_id: null, token_name: null }),
]

describe('Apple Pay › Recent attempts', () => {
  it('shows the three outcomes with time, merchant and the amount as received', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: THREE }) })
    renderWithProviders(<RecentAttempts />)
    const rows = within(await screen.findByRole('list', { name: 'Recent attempts' })).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('Added')).toHaveClass('ui-badge--pos')
    expect(rows[0]).toHaveTextContent("Lidl · '€12,50'")
    expect(rows[0]).toHaveTextContent('5m ago')
    expect(rows[0]).toHaveTextContent('iPhone')
    expect(within(rows[1]).getByText('Duplicate')).toHaveClass('ui-badge--warn')
    expect(rows[1]).toHaveTextContent("AB · '7.20'")
    expect(rows[1]).toHaveTextContent('3h ago')
    expect(within(rows[2]).getByText('Rejected')).toHaveClass('ui-badge--neg')
    expect(rows[2]).toHaveTextContent("No merchant · 'twelve euro fifty'")
    expect(rows[2]).toHaveTextContent('4d ago')
    expect(rows[2]).toHaveTextContent('HTTP 422')
  })

  it('the time is relative, with the exact time in the title and on tap', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: [THREE[0]] }) })
    renderWithProviders(<RecentAttempts />)
    const exact = exactTime(THREE[0].created_at)
    const time = await screen.findByRole('button', { name: `5m ago, ${exact}` })
    expect(time).toHaveAttribute('title', exact)
    expect(time).toHaveTextContent('5m ago')
    fireEvent.click(time)
    expect(time).toHaveTextContent(exact)
    expect(ago(minsAgo(0))).toBe('just now')
  })

  it('a rejected attempt shows its reason in full (the CSS that keeps it wrapping is pinned in attemptsCss.test.ts)', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: [THREE[2]] }) })
    renderWithProviders(<RecentAttempts />)
    const reason = await screen.findByText(LONG)
    expect(reason).toHaveClass('attempt__reason')
  })

  it('links to the transaction when there is one', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: THREE }) })
    renderWithProviders(<RecentAttempts />)
    const rows = within(await screen.findByRole('list', { name: 'Recent attempts' })).getAllByRole('listitem')
    expect(within(rows[0]).getByRole('link', { name: 'View transaction' })).toHaveAttribute('href', '/activity/t1')
    expect(within(rows[2]).queryByRole('link')).toBeNull()
  })

  it('the empty state says how to get one', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: [] }) })
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('No attempts yet. Run the Shortcut or pay with Apple Pay, then tap Refresh.')).toBeInTheDocument()
  })

  it('Refresh fetches again and shows the new attempt', async () => {
    let items = [THREE[1]]
    const fake = fakeApi({ [ATTEMPTS]: () => ({ items }) })
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('Duplicate')).toBeInTheDocument()
    items = [THREE[0], THREE[1]]
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(await screen.findByText('Added')).toBeInTheDocument()
    expect(fake.callsTo(ATTEMPTS)).toHaveLength(2)
  })

  it('is online only: offline it says so and Refresh is off', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: THREE }) }).down()
    setOnline(false)
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('Recent attempts need a connection.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled()
  })

  it('a failed load offers Try again', async () => {
    const fake = fakeApi({ [ATTEMPTS]: () => new Response(null, { status: 500 }) })
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('Couldn’t load the attempts.')).toBeInTheDocument()
    fake.on(ATTEMPTS, () => ({ items: [THREE[0]] }))
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Added')).toBeInTheDocument()
  })

  it('nothing is persisted: not the device cache, not web storage, and not kept after leaving', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: THREE }) })
    const view = renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('Added')).toBeInTheDocument()
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) }) // any cache write would have landed
    expect(await db.cache.count()).toBe(0)
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('Lidl')
    view.unmount()
    await waitFor(() => expect(JSON.stringify(view.client.getQueryCache().getAll().map((q) => q.state.data))).not.toContain('Lidl'))
  })
})
