import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi, reply, type FakeRequest } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { Activity } from './Activity'
import { BulkSheet } from './BulkSheet'
import type { Selection } from './selection'
import { REF, makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const BULK = 'POST /api/v1/transactions/bulk' as const

const RESULT = {
  dry_run: true, batch_id: null, matched: 3, changed: 2, unchanged: 1, total_out: 90, total_in: 0,
  skipped: [], bill: null, undo_until: null,
  buckets: [{
    bucket_id: 'b-bills', name: 'Bills', kind: 'monthly', budget: 300, period_start: '2026-10-01', period_end: '2026-10-31',
    spent_before: 100, spent_after: 190, moved_in: 90, moved_out: 0, outside_period: 1,
  }],
}
const ITEMS = [{ id: 'r1', name: 'Cosmote', direction: 'out' }, { id: 'r-sal', name: 'Salary', direction: 'in' }]
const ECHO = {
  [BULK]: (req: FakeRequest) => {
    const dry = (req.body as { dry_run: boolean }).dry_run
    return { ...RESULT, dry_run: dry, batch_id: dry ? null : 'batch1' } as never
  },
}

function renderSheet(selection: Selection, rows = [makeTxn()]) {
  const onApplied = vi.fn()
  renderActivity(
    <BulkSheet open selection={selection} rows={rows} refData={REF} items={ITEMS} initial="bucket" onApplied={onApplied} onClose={() => {}} />,
  )
  return onApplied
}

const pickBucket = (value: string) => fireEvent.change(screen.getByLabelText('Bucket'), { target: { value } })

describe('BulkSheet', () => {
  it('previews with dry_run, then applies with expected_count', async () => {
    const fake = fakeApi(ECHO)
    const onApplied = renderSheet({ kind: 'filter', filter: { missing_payer: true }, count: 3 })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('Bills: €100.00 → €190.00 of €300.00')).toBeInTheDocument()
    expect(screen.getByText('+1 from other periods, not in this budget')).toBeInTheDocument()
    expect(screen.getByText('1 already set')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Apply to 2' }))
    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    const [preview, apply] = fake.callsTo(BULK).map((c) => c.body as Record<string, unknown>)
    expect(preview).toMatchObject({ dry_run: true, select: { filter: { missing_payer: true } }, changes: { bucket_id: 'b-bills' } })
    expect(apply).toMatchObject({ dry_run: false, expected_count: 3 })
  })

  it('hand-picked rows apply without expected_count', async () => {
    const fake = fakeApi(ECHO)
    renderSheet({ kind: 'picked', ids: ['t1'] })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 2' }))
    await waitFor(() => expect(fake.callsTo(BULK)).toHaveLength(2))
    expect((fake.callsTo(BULK)[1].body as { expected_count: unknown }).expected_count).toBeNull()
  })

  it('a 409 on apply re-previews and shows the message', async () => {
    const bodies: { dry_run: boolean }[] = []
    fakeApi({
      [BULK]: (req) => {
        const body = req.body as { dry_run: boolean }
        bodies.push(body)
        if (!body.dry_run) return reply(409, { detail: 'The selection changed: 4 now match. Preview again.' })
        return { ...RESULT, matched: bodies.length > 1 ? 4 : 3 } as never
      },
    })
    renderSheet({ kind: 'filter', filter: { q: 'x' }, count: 3 })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 2' }))
    expect(await screen.findByText('The selection changed: 4 now match. Preview again.')).toBeInTheDocument()
    await waitFor(() => expect(bodies.filter((b) => b.dry_run)).toHaveLength(2))
  })

  it('apply guards with the preview\'s matched, not the feed total', async () => {
    let matched = 3
    const applies: { expected_count: unknown }[] = []
    fakeApi({
      [BULK]: (req) => {
        const body = req.body as { dry_run: boolean; expected_count: number | null }
        if (!body.dry_run) {
          applies.push(body)
          if (body.expected_count !== matched) return reply(409, { detail: `The selection changed: ${matched} now match. Preview again.` })
          return { ...RESULT, matched, dry_run: false, batch_id: 'b1' } as never
        }
        return { ...RESULT, matched } as never
      },
    })
    // The feed said 120 when "All" was tapped; the server matches 3.
    const onApplied = renderSheet({ kind: 'filter', filter: { q: 'x' }, count: 120 })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 2' }))
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce())
    expect(applies.map((a) => a.expected_count)).toEqual([3])
  })

  it('after a 409 the next apply uses the new matched and succeeds', async () => {
    let matched = 3
    const applies: { expected_count: unknown }[] = []
    fakeApi({
      [BULK]: (req) => {
        const body = req.body as { dry_run: boolean; expected_count: number | null }
        if (!body.dry_run) {
          applies.push(body)
          if (body.expected_count !== matched) return reply(409, { detail: 'The selection changed: 4 now match. Preview again.' })
          return { ...RESULT, matched, dry_run: false, batch_id: 'b1' } as never
        }
        return { ...RESULT, matched } as never
      },
    })
    const onApplied = renderSheet({ kind: 'filter', filter: { q: 'x' }, count: 3 })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await screen.findByRole('button', { name: 'Apply to 2' })
    matched = 4 // a row arrives between preview and apply
    fireEvent.click(screen.getByRole('button', { name: 'Apply to 2' }))
    expect(await screen.findByText('The selection changed: 4 now match. Preview again.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Apply to 2' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Apply to 2' }))
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce())
    expect(applies.map((a) => a.expected_count)).toEqual([3, 4])
  })

  it('a 400 stays open with the server detail; a network failure says nothing changed', async () => {
    const fake = fakeApi({ [BULK]: () => reply(400, { detail: 'That bucket is archived. Choose an active one.' }) })
    renderSheet({ kind: 'picked', ids: ['t1'] })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('That bucket is archived. Choose an active one.')).toBeInTheDocument()
    fake.down()
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText("Couldn't reach the server. Nothing was changed.")).toBeInTheDocument()
  })

  it('offers "Also move the bill" only by bill, off by default, disabled for an event bucket', () => {
    renderSheet({ kind: 'bill', billId: 'r1', count: 2 })
    expect(screen.queryByLabelText(/Also move the bill/)).toBeNull()
    pickBucket('b-day')
    expect((screen.getByLabelText(/Also move the bill/) as HTMLInputElement).checked).toBe(false)
    pickBucket('b-trip')
    expect(screen.getByLabelText(/Also move the bill/)).toBeDisabled()
  })

  it('hides the bill toggle for an in item and for hand-picked rows', () => {
    renderSheet({ kind: 'bill', billId: 'r-sal', count: 2 })
    pickBucket('b-day')
    expect(screen.queryByLabelText(/Also move the bill/)).toBeNull()
  })

  it('offers "No bucket (Fixed cost)" only when every row is a bucket-less Fixed cost', () => {
    const fixed = makeTxn({ bucket_id: null, recurring_bill_id: 'r1' })
    renderSheet({ kind: 'picked', ids: [fixed.id] }, [fixed])
    expect(screen.getByRole('option', { name: 'No bucket (Fixed cost)' })).toBeInTheDocument()
  })

  it('never offers it with a bucketed bill payment in the selection', () => {
    const fixed = makeTxn({ bucket_id: null, recurring_bill_id: 'r1' })
    const paid = makeTxn({ bucket_id: 'b-bills', recurring_bill_id: 'r1' })
    renderSheet({ kind: 'picked', ids: [fixed.id, paid.id] }, [fixed, paid])
    expect(screen.queryByRole('option', { name: /No bucket/ })).toBeNull()
  })
})

describe('BulkSheet from Activity', () => {
  it('a BulkBar action opens the sheet; apply ends selection with a 10 s "Moved N payments" toast', async () => {
    const row = makeTxn({ notes: 'one' })
    const fake = fakeApi({ ...refRoutes(), 'GET /api/v1/transactions': () => pageOf([row]), ...ECHO })
    renderActivity(<Activity />)
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    fireEvent.click(screen.getByRole('button', { name: 'Bucket' }))
    expect(await screen.findByRole('dialog', { name: 'Change 1 selected' })).toBeInTheDocument()
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 2' }))
    expect(await screen.findByText('Moved 2 payments')).toBeInTheDocument()
    expect(screen.queryByRole('toolbar', { name: /Bulk actions/ })).toBeNull()
    expect((fake.callsTo(BULK)[0].body as { select: unknown }).select).toEqual({ ids: [row.id] })
  })
})
