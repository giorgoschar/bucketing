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
const summary = (o: Record<string, string | null>, unknown = 0) =>
  JSON.stringify({
    ...Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v === null ? { type: 'missing' } : { type: 'text', value: v }])),
    unknown_keys: unknown,
  })
const attempt = (over: Partial<IngestAttempt>): IngestAttempt => ({
  id: 'a1', created_at: minsAgo(5), status: 201, outcome: 'created', detail: null,
  payload: summary({ merchant: 'Lidl', amount: '€12,50' }), token_prefix: 'tam_ab12', transaction_id: 't1', ...over,
})
const THREE = [
  attempt({}),
  attempt({ id: 'a2', created_at: minsAgo(180), status: 200, outcome: 'duplicate', detail: 'Same purchase 1 min earlier', payload: summary({ merchant: 'AB', amount: '7.20' }), transaction_id: 't0' }),
  attempt({ id: 'a3', created_at: minsAgo(60 * 24 * 4), status: 422, outcome: 'rejected', detail: LONG, payload: summary({ merchant: null, amount: 'twelve euro fifty' }, 2), transaction_id: null, token_prefix: null }),
]

describe('Apple Pay › Recent attempts', () => {
  it('shows the three outcomes with time, merchant and the amount as received', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: THREE }) })
    renderWithProviders(<RecentAttempts />)
    const rows = within(await screen.findByRole('list', { name: 'Recent attempts' })).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('Added')).toHaveClass('ui-badge--pos')
    expect(rows[0]).toHaveTextContent('merchant: Lidl')
    expect(rows[0]).toHaveTextContent('amount: €12,50')
    expect(rows[0]).toHaveTextContent('5m ago')
    expect(rows[0]).toHaveTextContent('tam_ab12')
    expect(within(rows[1]).getByText('Duplicate')).toHaveClass('ui-badge--warn')
    expect(rows[1]).toHaveTextContent('merchant: AB')
    expect(rows[1]).toHaveTextContent('amount: 7.20')
    expect(rows[1]).toHaveTextContent('3h ago')
    expect(within(rows[2]).getByText('Rejected')).toHaveClass('ui-badge--neg')
    expect(rows[2]).toHaveTextContent('merchant: not sent')
    expect(rows[2]).toHaveTextContent('amount: twelve euro fifty')
    expect(rows[2]).toHaveTextContent('other keys: 2')
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
    expect(reason).toHaveTextContent(LONG)
  })

  it('an older entry (payload null) says its details were not kept', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: [attempt({ id: 'old', payload: null, detail: '[older entry]', status: 422, outcome: 'rejected', transaction_id: null })] }) })
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('Older entry: details not kept')).toBeInTheDocument()
  })

  it('a summary that is not JSON is shown as plain text', async () => {
    const text = 'not a JSON object (12 bytes, text/plain)'
    fakeApi({ [ATTEMPTS]: () => ({ items: [attempt({ payload: text })] }) })
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText(text)).toBeInTheDocument()
  })

  it('a JSON value that is not a summary is shown as plain text, never as markup', async () => {
    const text = '[1,2,{"a":"<img src=x onerror=alert(1)>"}]'
    fakeApi({ [ATTEMPTS]: () => ({ items: [attempt({ payload: text })] }) })
    const view = renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText(text)).toBeInTheDocument()
    expect(view.container.querySelector('img')).toBeNull()
  })

  it('summary values are rendered as text, never HTML', async () => {
    const evil = '<img src=x onerror=alert(1)>'
    fakeApi({ [ATTEMPTS]: () => ({ items: [attempt({ payload: summary({ merchant: evil, amount: '1' }) })] }) })
    const view = renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText(`merchant: ${evil}`)).toBeInTheDocument()
    expect(view.container.querySelector('img')).toBeNull()
  })

  it('null, missing and structured fields read as one line each', async () => {
    const payload = JSON.stringify({
      merchant: { type: 'null' }, amount: { type: 'number', value: '12.5' }, card: { type: 'record', value: 'keys: Name' },
      notes: { type: 'list', value: '2 items' }, unknown_keys: 0,
    })
    fakeApi({ [ATTEMPTS]: () => ({ items: [attempt({ payload })] }) })
    renderWithProviders(<RecentAttempts />)
    const row = (await screen.findByRole('list', { name: 'Recent attempts' })).querySelector('li')!
    expect(row).toHaveTextContent('merchant: empty')
    expect(row).toHaveTextContent('amount: 12.5')
    expect(row).toHaveTextContent('card: keys: Name')
    expect(row).toHaveTextContent('notes: 2 items')
    expect(row).not.toHaveTextContent('other keys')
  })

  it('shows the four outcomes by name', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: [attempt({ id: 'c', outcome: 'classified' })] }) })
    renderWithProviders(<RecentAttempts />)
    expect(await screen.findByText('Category set')).toHaveClass('ui-badge--pos')
  })

  it('does not repeat what the badge or the older-entry line already says', async () => {
    fakeApi({ [ATTEMPTS]: () => ({ items: [
      attempt({ id: 'ok', detail: 'created' }),
      attempt({ id: 'old', payload: null, detail: '[older entry]', status: 422, outcome: 'rejected', transaction_id: null }),
    ] }) })
    renderWithProviders(<RecentAttempts />)
    const rows = within(await screen.findByRole('list', { name: 'Recent attempts' })).getAllByRole('listitem')
    expect(rows[0]).not.toHaveTextContent('created')
    expect(rows[1]).not.toHaveTextContent('[older entry]')
    expect(rows[1]).toHaveTextContent('Older entry: details not kept')
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
