import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi, reply } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { Activity } from './Activity'
import { RecentBulk } from './RecentBulk'
import { Detail } from './Detail'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const UNDO = 'POST /api/v1/transactions/bulk/{batch_id}/undo' as const

const RECENT = [
  { id: 'b2', created_at: '2026-10-07T09:00:00', created_by: 'Giorgos', summary: 'Bucket → Bills · 12 transactions', row_count: 12, undone_at: null, can_undo: true },
  { id: 'b1', created_at: '2026-10-05T09:00:00', created_by: 'Maria', summary: 'Payer → Maria · 3 transactions', row_count: 3, undone_at: '2026-10-05T10:00:00', can_undo: false },
]

describe('undo', () => {
  it('Recent bulk changes lists the last batches; Undo reports skips', async () => {
    const fake = fakeApi({
      'GET /api/v1/transactions/bulk': () => RECENT as never,
      [UNDO]: () => ({ restored: 11, skipped: [{ id: 'x', code: 'changed_since', reason: 'Changed since' }], bill_restored: false }) as never,
    })
    renderActivity(<RecentBulk open onClose={() => {}} />)
    expect(await screen.findByText('Bucket → Bills · 12 transactions')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(1) // only the one that can
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Restored 11 · 1 changed since, left as they are')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Details' })).toBeInTheDocument()
    expect(fake.callsTo(UNDO).map((c) => c.path)).toEqual(['/api/v1/transactions/bulk/b2/undo'])
  })

  it('a 409 shows the detail', async () => {
    fakeApi({
      'GET /api/v1/transactions/bulk': () => RECENT as never,
      [UNDO]: () => reply(409, { detail: 'Changes can be undone for 24 hours.' }),
    })
    renderActivity(<RecentBulk open onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Changes can be undone for 24 hours.')).toBeInTheDocument()
  })

  it('the detail history offers "Undo this change" for an undoable bulk event', async () => {
    const row = makeTxn({ id: 'h1', merchant: 'Cosmote' })
    const fake = fakeApi({
      ...refRoutes(),
      'GET /api/v1/transactions/{txn_id}': () => row,
      'GET /api/v1/recurring/entries': () => [],
      'GET /api/v1/transactions/{txn_id}/history': () =>
        ({ events: [{ at: '2026-10-07T09:00:00', kind: 'bulk_change', by: 'Giorgos', text: 'Bucket: Day to day → Bills', batch_id: 'b2', can_undo: true }] }) as never,
      [UNDO]: () => ({ restored: 1, skipped: [], bill_restored: false }) as never,
    })
    renderActivity(<Detail />, { route: '/activity/h1', path: '/activity/:id' })
    fireEvent.click(await screen.findByRole('button', { name: 'Undo this change' }))
    await waitFor(() => expect(fake.callsTo(UNDO).map((c) => c.path)).toEqual(['/api/v1/transactions/bulk/b2/undo']))
    expect(await screen.findByText('Restored 1')).toBeInTheDocument()
  })
})

describe('undo from the apply toast', () => {
  it('the "Moved N payments" toast has Undo, which undoes that batch', async () => {
    const row = makeTxn({ notes: 'one' })
    const fake = fakeApi({
      ...refRoutes(),
      'GET /api/v1/transactions': () => pageOf([row]),
      'POST /api/v1/transactions/bulk': (req) => ({
        dry_run: (req.body as { dry_run: boolean }).dry_run, batch_id: 'b9', matched: 1, changed: 1, unchanged: 0,
        total_out: 10, total_in: 0, skipped: [], bill: null, undo_until: null, buckets: [],
      }) as never,
      [UNDO]: () => ({ restored: 1, skipped: [], bill_restored: false }) as never,
    })
    renderActivity(<Activity />)
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    fireEvent.click(screen.getByRole('button', { name: 'Bucket' }))
    fireEvent.change(await screen.findByLabelText('Bucket'), { target: { value: 'b-bills' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 1' }))
    expect(await screen.findByText('Moved 1 payment')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(fake.callsTo(UNDO).map((c) => c.path)).toEqual(['/api/v1/transactions/bulk/b9/undo']))
    expect(await screen.findByText('Restored 1')).toBeInTheDocument()
  })

  it('the More menu opens Recent bulk changes', async () => {
    fakeApi({ ...refRoutes(), 'GET /api/v1/transactions': () => pageOf([]), 'GET /api/v1/transactions/bulk': () => RECENT as never })
    renderActivity(<Activity />)
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Recent bulk changes/ }))
    expect(await screen.findByText('Bucket → Bills · 12 transactions')).toBeInTheDocument()
  })
})
