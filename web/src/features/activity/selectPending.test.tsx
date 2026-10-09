import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, TEST_IDENTITY } from '../../test/render'
import { Activity } from './Activity'
import { _resetHeldForTests } from './heldDeletes'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

// P3 final review M1: an "All" selection sent the filter, so the server also changed rows the phone still
// holds a queued edit for (a replay later reverts the bulk change) or is about to delete (swipe hold).
afterEach(async () => {
  _resetHeldForTests()
  await resetTestEnv()
})

const BULK = 'POST /api/v1/transactions/bulk' as const
const rows = [makeTxn({ notes: 'one' }), makeTxn({ notes: 'two' }), makeTxn({ notes: 'three' })]
const result = (dry: boolean) => ({
  dry_run: dry, batch_id: 'b1', matched: 2, changed: 2, unchanged: 0, total_out: 20, total_in: 0,
  skipped: [], bill: null, undo_until: null, buckets: [],
}) as never

function setup({ total = rows.length, route = '/activity' } = {}) {
  const fake = fakeApi({
    ...refRoutes({ no_payer: 3, duplicate_groups: 0 }),
    'GET /api/v1/transactions': () => pageOf(rows, { total }),
    [BULK]: (req) => result((req.body as { dry_run: boolean }).dry_run),
  })
  renderActivity(<Activity />, { route })
  return fake
}
async function queueEdit(id: string) {
  setIdentity(TEST_IDENTITY)
  await enqueue({ method: 'PUT', path: `/api/v1/transactions/${id}`, body: { type: 'expense', amount: '10.00', currency: 'EUR', notes: 'x', transaction_date: rows[1].transaction_date } })
}
async function selectMode() {
  fireEvent.click(await screen.findByRole('button', { name: 'More' }))
  fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
}
async function previewBody(fake: ReturnType<typeof setup>) {
  fireEvent.click(screen.getByRole('button', { name: 'Bucket' }))
  fireEvent.change(await screen.findByLabelText('Bucket'), { target: { value: 'b-bills' } })
  fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
  await waitFor(() => expect(fake.callsTo(BULK)).toHaveLength(1))
  return fake.callsTo(BULK)[0].body as { select: Record<string, unknown> }
}

describe('Select › All leaves out pending and mid-delete rows', () => {
  it('with a queued edit and every row loaded, All picks the other rows by id', async () => {
    await queueEdit(rows[1].id)
    const fake = setup()
    expect(await screen.findByText('Waiting to sync')).toBeInTheDocument()
    await selectMode()
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    const body = await previewBody(fake)
    expect(body.select).toEqual({ ids: [rows[0].id, rows[2].id] })
  })

  it('a row in its swipe-delete hold is left out too', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const fake = setup()
    const deletes = await screen.findAllByRole('button', { name: 'Delete' })
    fireEvent.click(deletes[1]) // "two"
    await selectMode()
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    const body = await previewBody(fake)
    expect(body.select).toEqual({ ids: [rows[0].id, rows[2].id] })
    act(() => vi.advanceTimersByTime(0))
  })

  it('with pending rows and more to load, All is off and says why', async () => {
    await queueEdit(rows[1].id)
    setup({ total: 120 })
    expect(await screen.findByText('Waiting to sync')).toBeInTheDocument()
    await selectMode()
    expect(screen.getByRole('button', { name: 'All' })).toBeDisabled()
    expect(screen.getByText('All is off until the changes waiting to sync are sent.')).toBeInTheDocument()
  })

  it('"Select all N" under No payer also picks by id when a row is pending', async () => {
    await queueEdit(rows[1].id)
    const fake = setup({ route: '/activity?missing_payer=1' })
    expect(await screen.findByText('Waiting to sync')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Select all 2' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    expect((await previewBody(fake)).select).toEqual({ ids: [rows[0].id, rows[2].id] })
  })

  it('with nothing pending, All still selects by filter on the server (count from the server)', async () => {
    const fake = setup({ total: 120, route: '/activity?q=o&all=1' })
    await selectMode()
    fireEvent.click(await screen.findByRole('button', { name: 'All' }))
    expect(screen.getByText('120 selected')).toBeInTheDocument()
    expect((await previewBody(fake)).select).toEqual({ filter: { q: 'o' } })
  })
})
