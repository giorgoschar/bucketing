import { useRef, useState } from 'react'
import { ApiError } from '../../data/http'
import { useOnline } from '../../data/online'
import { Sheet } from '../../ui/Sheet'
import { BulkPreview } from './BulkPreview'
import { METHOD_LABELS } from './format'
import {
  applyBulk, type BulkChanges, type BulkReq, type BulkResult, previewBulk, type RecurringItem, type RefData, type Txn,
} from './hooks'
import { OWN_SHARE } from './pickers'
import { expectedCount, type Selection, selectedCount, toSelect } from './selection'

export type BulkField = 'bucket' | 'category' | 'payer' | 'method'
const KEEP = '__keep'
const NONE = '__none'
const LEAVE: Record<BulkField, string> = { bucket: KEEP, category: KEEP, payer: KEEP, method: KEEP }

type Props = {
  open: boolean
  selection: Selection
  rows: Txn[] // the loaded rows (hand-picked rule checks)
  refData?: RefData
  items?: RecurringItem[]
  initial: BulkField
  onApplied: (result: BulkResult, req: BulkReq) => void
  onClose: () => void
}

/** Spec §4.5: "No bucket" when every selected row is income; "No bucket (Fixed cost)" only when every
 * selected row is a bucket-less Fixed cost. A selection with any bucketed bill payment never offers it. */
function noBucketLabel(sel: Selection, rows: Txn[], items?: RecurringItem[]): string | null {
  if (sel.kind === 'filter') return sel.filter.type === 'income' ? 'No bucket' : sel.filter.fixed ? 'No bucket (Fixed cost)' : null
  if (sel.kind === 'bill') return items?.find((i) => i.id === sel.billId)?.direction === 'in' ? 'No bucket' : null
  if (sel.kind !== 'picked') return null
  const picked = rows.filter((r) => sel.ids.includes(r.id))
  if (picked.length !== sel.ids.length || picked.length === 0) return null
  if (picked.every((r) => r.type === 'income')) return 'No bucket'
  if (picked.every((r) => r.type === 'expense' && r.recurring_bill_id && !r.bucket_id)) return 'No bucket (Fixed cost)'
  return null
}

export function BulkSheet({ open, selection, rows, refData, items, initial, onApplied, onClose }: Props) {
  const isOnline = useOnline()
  const [values, setValues] = useState<Record<BulkField, string>>(LEAVE)
  const [moveBill, setMoveBill] = useState(false)
  const [preview, setPreview] = useState<BulkResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const first = useRef<HTMLSelectElement>(null)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    // A fresh sheet each time it opens (state adjusted during render, not in an effect).
    setWasOpen(open)
    if (open) {
      setValues(LEAVE)
      setPreview(null)
      setError(null)
      setMoveBill(false)
    }
  }

  const noBucket = noBucketLabel(selection, rows, items)
  const target = refData?.buckets.find((b) => b.id === values.bucket)
  const isEvent = target?.kind === 'event'
  const bill = selection.kind === 'bill' ? items?.find((i) => i.id === selection.billId) : undefined
  const showMoveBill = !!bill && bill.direction !== 'in' && values.bucket !== KEEP
  const set = (f: BulkField, v: string) => {
    setValues((s) => ({ ...s, [f]: v }))
    setPreview(null)
    setError(null)
  }

  const changes = (): BulkChanges => {
    const c: BulkChanges = {}
    if (values.bucket !== KEEP) c.bucket_id = values.bucket === NONE ? null : values.bucket
    if (values.category !== KEEP) c.category_id = values.category === NONE ? null : values.category
    if (values.payer !== KEEP) c.payer = values.payer === OWN_SHARE ? { mode: 'own_share' } : { mode: 'single', user_id: values.payer }
    if (values.method !== KEEP) c.payment_method = values.method
    return c
  }
  const req = (): BulkReq => ({ select: toSelect(selection), changes: changes(), move_bill: showMoveBill && moveBill && !isEvent })

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const doPreview = () => run(async () => setPreview(await previewBulk(req())))
  const doApply = () =>
    run(async () => {
      const r = req()
      // The guard is what the user saw: the preview's matched (the feed's total can differ, e.g. pending rows).
      // After a 409 the re-preview below replaces `preview`, so the next apply sends the new count.
      const expected = expectedCount(selection) === null ? null : (preview?.matched ?? null)
      try {
        onApplied(await applyBulk(r, expected), r)
      } catch (e) {
        // The selection changed under us: show the new numbers, keep the server's message.
        if (e instanceof ApiError && e.status === 409) setPreview(await previewBulk(r))
        throw e
      }
    })

  const billMoves = !!preview?.bill && preview.bill.bucket_before !== preview.bill.bucket_after
  const nothing = !!preview && preview.changed === 0 && !billMoves
  const untouched = Object.values(values).every((v) => v === KEEP)
  const field = (f: BulkField, label: string, options: { value: string; label: string }[]) => (
    <label className="ui-field bulk-field">
      <span className="ui-field__label">{label}</span>
      <select ref={f === initial ? first : undefined} className="ui-input" value={values[f]} onChange={(e) => set(f, e.target.value)}>
        <option value={KEEP}>Leave as is</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )

  const count = selectedCount(selection)
  const footer = (
    <div className="bulk-sheet__foot">
      {!isOnline && <p className="bulk-sheet__why">Needs a connection</p>}
      {!preview ? (
        <button type="button" className="btn btn--primary btn--block btn--lg" disabled={busy || !isOnline || untouched} onClick={doPreview}>
          {busy ? 'Checking…' : 'Preview'}
        </button>
      ) : (
        <button type="button" className="btn btn--primary btn--block btn--lg" disabled={busy || !isOnline || nothing} onClick={doApply}>
          {nothing ? 'Nothing to change' : `Apply to ${preview.changed}`}
        </button>
      )}
    </div>
  )

  return (
    <Sheet open={open} onClose={onClose} title={`Change ${count} selected`} footer={footer} initialFocus={first}>
      <div className="bulk-sheet">
        {field('bucket', 'Bucket', [
          ...(refData?.buckets.filter((b) => b.status === 'active')
            .map((b) => ({ value: b.id, label: b.kind === 'event' ? `${b.name} (event)` : b.name })) ?? []),
          ...(noBucket ? [{ value: NONE, label: noBucket }] : []),
        ])}
        {showMoveBill && (
          <label className="ck-toggle-row bulk-switch">
            <span className="ck-toggle-row__text">
              <span className="ck-toggle-row__label">Also move the bill, so future payments go here</span>
              {isEvent && <span className="ck-toggle-row__hint">A bill can't move into an event bucket</span>}
            </span>
            <input type="checkbox" role="switch" className="bulk-switch__input" checked={moveBill && !isEvent} disabled={isEvent}
              onChange={(e) => { setMoveBill(e.target.checked); setPreview(null) }} />
            <span className={moveBill && !isEvent ? 'toggle on' : 'toggle'} aria-hidden="true" />
          </label>
        )}
        {field('category', 'Category', [
          ...(refData?.categories.map((c) => ({ value: c.id, label: c.name })) ?? []),
          { value: NONE, label: 'No category' },
        ])}
        {field('payer', 'Payer', [
          ...(refData?.members.map((m) => ({ value: m.user_id, label: m.display_name ?? 'Member' })) ?? []),
          { value: OWN_SHARE, label: 'Each paid their own share' },
        ])}
        {field('method', 'Method', Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label })))}

        {error && <p className="bulk-sheet__error" role="alert">{error}</p>}
        {preview && <BulkPreview result={preview} rows={rows} refData={refData} />}
      </div>
    </Sheet>
  )
}
