import { useState } from 'react'
import { api } from '../../api/client'
import type { components } from '../../api/schema'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { keys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import { parseAmount } from '../../ui/format'
import { Segmented } from '../../ui/Segmented'
import { Sheet } from '../../ui/Sheet'
import { useArchiveBucket } from './hooks'
import './items/items.css'

type BucketIn = components['schemas']['BucketIn']
/** A row of GET /buckets: the PUT replaces every field, so an edit sends the stored ones back. */
export type RawBucket = BucketIn & { id: string; type: string; kind: string; color: string; icon: string }

export function useRawBuckets() {
  return useCachedQuery(keys.bucketsFull(), async (signal) => (await unwrap(api.GET('/api/v1/buckets', { signal }))) as unknown as RawBucket[])
}

const KINDS = [{ value: 'monthly', label: 'Monthly' }, { value: 'event', label: 'Trip or event' }] as const
type Kind = (typeof KINDS)[number]['value']

export function BucketSheet({ open, bucket, onClose }: { open: boolean; bucket: RawBucket | null; onClose(): void }) {
  return (
    <Sheet open={open} onClose={onClose} title={bucket ? 'Edit bucket' : 'New bucket'}>
      {open && <Body key={bucket?.id ?? 'new'} bucket={bucket} onClose={onClose} />}
    </Sheet>
  )
}

function Body({ bucket, onClose }: { bucket: RawBucket | null; onClose(): void }) {
  const act = useOnlineAction()
  const archive = useArchiveBucket()
  const [name, setName] = useState(bucket?.name ?? '')
  const [kind, setKind] = useState<Kind>(bucket?.kind === 'event' ? 'event' : 'monthly')
  const [budget, setBudget] = useState(bucket?.budget == null ? '' : String(bucket.budget))
  const [start, setStart] = useState(bucket?.start_date ?? '')
  const [end, setEnd] = useState(bucket?.end_date ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    const amount = parseAmount(budget)
    const event = kind === 'event'
    const msg = !name.trim() ? 'Give the bucket a name.'
      : amount === undefined ? 'The budget is not a valid amount.'
      : event && (!start || !end) ? 'A trip or event needs a start and an end date.'
      : event && end < start ? 'The end date is before the start date.'
      : null
    if (msg) return setProblem(msg)
    setProblem(null)
    const body: BucketIn = {
      type: 'custom', color: '#6366f1', icon: '🪣', show_income: true, enable_settlement: false, // new-bucket defaults; an edit overwrites them
      ...(bucket ?? {}),
      name: name.trim(), kind, budget: amount ?? null,
      // Monthly clears the dates; the server keeps stored ones when the field is left out.
      start_date: event ? start : null, end_date: event ? end : null,
    }
    setBusy(true)
    const opts = { invalidates: [keys.plan.all, keys.buckets(), keys.insights.all, keys.home.all], success: bucket ? 'Saved' : 'Bucket added' }
    const out = await act(() => bucket
      ? api.PUT('/api/v1/buckets/{bucket_id}', { params: { path: { bucket_id: bucket.id } }, body })
      : api.POST('/api/v1/buckets', { body }), opts)
    setBusy(false)
    if (out.ok) onClose()
    else if (out.kind === 'rejected') setProblem(out.message)
  }

  const confirmArchive = async () => {
    if (!bucket) return
    setBusy(true)
    const out = await archive(bucket.id)
    setBusy(false)
    if (out.ok) onClose()
    else if (out.kind === 'rejected') setProblem(out.message)
  }

  return (
    <form className="items-form" noValidate onSubmit={(e) => { e.preventDefault(); void save() }}>
      {problem && <p className="items-form__problem" role="alert">{problem}</p>}
      <label className="ui-field">
        <span className="ui-field__label">Name</span>
        <input className="ui-input" value={name} maxLength={100} autoComplete="off" onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="ui-field">
        <span className="ui-field__label" aria-hidden="true">Type</span>
        <Segmented label="Type" options={KINDS} value={kind} onChange={setKind} />
      </div>
      {kind === 'event' && (
        <div className="items-form__row items-form__row--even">
          <label className="ui-field">
            <span className="ui-field__label">Starts</span>
            <input type="date" className="ui-input" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Ends</span>
            <input type="date" className="ui-input" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>
      )}
      <label className="ui-field">
        <span className="ui-field__label">Budget (optional)</span>
        <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" placeholder="No limit" value={budget}
          onChange={(e) => setBudget(e.target.value)} />
      </label>
      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={busy}>{bucket ? 'Save' : 'Add bucket'}</button>
      {bucket && !confirming && (
        <button type="button" className="btn btn--danger btn--block" disabled={busy} onClick={() => setConfirming(true)}>Archive</button>
      )}
      {bucket && confirming && (
        <div className="plan-archive">
          <p className="plan-archive__text">{`Archive ${bucket.name}? There is no undo: it leaves Plan and the new app.`}</p>
          <div className="plan-archive__actions">
            <button type="button" className="btn" onClick={() => setConfirming(false)}>Cancel</button>
            <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void confirmArchive()}>Confirm archive</button>
          </div>
        </div>
      )}
    </form>
  )
}
