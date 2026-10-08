import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../data/http'
import { keys } from '../../data/keys'
import { useOnline } from '../../data/online'
import { Badge } from '../../ui/Badge'
import { ChevronLeftIcon, ChevronRightIcon } from '../../ui/icons'
import { Money } from '../../ui/Money'
import { useToast } from '../../ui/Toast'
import { ToggleRow } from '../../ui/ToggleRow'
import { RECEIPT_ACCEPT, receiptProblem } from '../composer/receipt'
import { EntrySheet } from '../plan/EntrySheet'
import { dayLabel, METHOD_LABELS, rowTitle } from './format'
import {
  type HistoryEvent, type RefData, type Txn, type TxnPage, type TxnPatch, receiptUrl, uploadReceipt,
  useEditTransaction, useHistory, useLinkedEntry, useRefData, useTransaction,
} from './hooks'
import { useHeldDeletes } from './heldDeletes'
import { NotesSheet } from './NotesSheet'
import { OptionSheet } from './OptionSheet'
import { toPendingTxn, usePendingActivity } from './pending'
import { bucketOptions, OWN_SHARE, payerOptions, payerPatch } from './pickers'
import { useDeleteWithUndo } from './useDeleteWithUndo'
import { useUndoBulk } from './useUndoBulk'
import './activity.css' // a cold deep link to /activity/:id never loads Activity.tsx

type Picker = null | 'category' | 'bucket' | 'payer' | 'method' | 'notes'

const IMAGE = /\.(jpe?g|png|gif|webp)$/i
const TIME = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function FieldRow({ label, value, onClick, disabled }: { label: string; value: string; onClick: () => void; disabled?: boolean }) {
  return (
    <li>
      <button type="button" className="ui-row field-row" onClick={onClick} disabled={disabled} aria-label={`${label}, ${value}`}>
        <span className="ui-row__main">
          <span className="field-row__label">{label}</span>
          <span className="ui-row__title">{value}</span>
        </span>
        {!disabled && <span className="field-row__chev" aria-hidden="true"><ChevronRightIcon /></span>}
      </button>
    </li>
  )
}

export function HistoryList({ id, renderAction }: { id: string; renderAction?: (e: HistoryEvent) => ReactNode }) {
  const events = useHistory(id).data?.events ?? []
  if (events.length === 0) return null
  return (
    <section className="detail__section" aria-labelledby="history-h">
      <h2 className="detail__h" id="history-h">History</h2>
      <ol className="ui-list history">
        {events.map((e, i) => (
          <li key={`${e.kind}-${e.at}-${i}`} className="ui-row history__row">
            <span className="ui-row__main">
              <span className="history__text">{e.text}</span>
              <span className="ui-row__sub">{TIME.format(new Date(e.at))}{e.by ? ` · ${e.by}` : ''}</span>
            </span>
            {renderAction?.(e)}
          </li>
        ))}
      </ol>
    </section>
  )
}

function names(t: Txn, ref?: RefData) {
  return {
    category: ref?.categories.find((c) => c.id === t.category_id)?.name ?? 'None',
    bucket: ref?.buckets.find((b) => b.id === t.bucket_id)?.name
      ?? (t.recurring_bill_id && t.type === 'expense' ? 'No bucket (Fixed cost)' : 'No bucket'),
    payer: t.payer_mode === 'own_share'
      ? 'Each paid their own share'
      : ref?.members.find((m) => m.user_id === t.paid_by)?.display_name ?? 'No payer',
  }
}

const SHARE_TINTS = ['var(--c3)', 'var(--c2)', 'var(--c1)', 'var(--c4)']

function Shares({ t, refData }: { t: Txn; refData?: RefData }) {
  const total = t.splits.reduce((s, x) => s + x.amount, 0) || 1
  const who = (id: string) => refData?.members.find((m) => m.user_id === id)?.display_name ?? 'Member'
  return (
    <section className="ui-card detail__shares" aria-labelledby="shares-h">
      <div className="detail__between">
        <h2 className="detail__h" id="shares-h">Shares</h2>
        <span className="detail__muted num">{t.splits.map((s) => Math.round((s.amount / total) * 100)).join(' / ')}</span>
      </div>
      <div className="share-bar" aria-hidden="true">
        {t.splits.map((s, i) => <span key={s.user_id} style={{ flex: s.amount, background: SHARE_TINTS[i % SHARE_TINTS.length] }} />)}
      </div>
      <ul className="share-list">
        {t.splits.map((s, i) => (
          <li key={s.user_id} className="detail__between">
            <span className="share-who">
              <span className="share-dot" style={{ background: SHARE_TINTS[i % SHARE_TINTS.length] }} aria-hidden="true" />
              {who(s.user_id)}
            </span>
            <span className="num"><Money amount={s.amount} currency={t.currency ?? 'EUR'} /></span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The row as a cached feed page holds it (P3 M4): offline, a row seen in Activity but never opened. */
function listedRow(qc: QueryClient, id: string): Txn | undefined {
  for (const [, data] of qc.getQueriesData<TxnPage>({ queryKey: keys.transactions.all })) {
    const hit = data && typeof data === 'object' && 'items' in data ? data.items.find((t) => t.id === id) : undefined
    if (hit) return hit
  }
  return undefined
}

export function Detail() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const online = useOnline()
  const toast = useToast()
  const ref = useRefData()
  const pending = usePendingActivity()
  const held = useHeldDeletes()
  const query = useTransaction(id)
  const qc = useQueryClient()
  const edit = useEditTransaction()
  const deleteWithUndo = useDeleteWithUndo()
  const undo = useUndoBulk()
  const linked = useLinkedEntry(query.data)
  const [picker, setPicker] = useState<Picker>(null)
  const [entryOpen, setEntryOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [undoing, setUndoing] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)

  // Back to where the user came from (keeps the feed's filters); a cold deep link goes to the feed.
  const back = () => (location.key !== 'default' ? navigate(-1) : navigate('/activity'))
  const bar = (end?: ReactNode) => (
    <header className="detail-bar">
      <button type="button" className="ui-iconbtn ui-iconbtn--bare detail-bar__back" aria-label="Back" onClick={back}>
        <ChevronLeftIcon />
      </button>
      {end}
    </header>
  )

  const created = pending.creates.find((p) => p.id === id)
  const queuedEdit = pending.edits.get(id)
  const gone = held.has(id) || pending.hidden.has(id)
  const base = query.data ?? listedRow(qc, id)
  const t: Txn | undefined = created ?? (base && queuedEdit ? toPendingTxn(queuedEdit, base) : base)
  if (!t || gone) {
    // Gone only when the server says so (404) or it is deleted here; offline is "not saved", any other
    // failure can be retried.
    const error = qc.getQueryState(keys.transactions.one(id))?.error
    const notFound = gone || (error instanceof ApiError && error.status === 404)
    const failed = !notFound && query.isError && !query.offline
    const unsaved = !notFound && !failed && query.noData
    return (
      <>
        {bar()}
        {failed ? (
          <p className="screen__note detail__note detail__retry">
            <span>Couldn’t load this transaction.</span>
            <button type="button" className="btn btn--sm" onClick={query.refetch}>Retry</button>
          </p>
        ) : (
          <p className="screen__note detail__note" aria-busy={!notFound && !unsaved}>
            {notFound ? 'This transaction is gone.' : unsaved ? 'This transaction isn’t saved on this phone.' : 'Loading…'}
          </p>
        )}
      </>
    )
  }
  const readOnly = !!created || !!queuedEdit
  const n = names(t, ref)
  const save = (patch: TxnPatch) => void edit.run({ txn: t, patch })
  const sign = t.type === 'income' ? 1 : t.type === 'expense' ? -1 : 0
  const icon = ref?.categories.find((c) => c.id === t.category_id)?.icon ?? '•'
  const method = METHOD_LABELS[t.payment_method] ?? t.payment_method

  const undoOnce = async (batchId: string) => {
    if (undoing) return
    setUndoing(batchId)
    try {
      await undo(batchId)
    } finally {
      setUndoing(null)
    }
  }

  const attach = async (f: File) => {
    const problem = receiptProblem(f)
    if (problem) return toast.show(problem, { tone: 'error' })
    setUploading(true)
    try {
      await uploadReceipt(t.id, f)
      query.refetch()
    } catch (err) {
      toast.show((err as Error).message, { tone: 'error' })
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      {bar(!readOnly && <Link className="btn btn--ghost btn--sm" to={`/edit/${encodeURIComponent(t.id)}`}>Edit</Link>)}
      <section className="screen detail">
        <header className="detail__head">
          <span className="detail__ico" aria-hidden="true">{icon}</span>
          <h1 className="detail__title">{rowTitle(t, ref)}</h1>
          <p className={sign > 0 ? 'detail__amt num ui-pos' : 'detail__amt num'}>
            <Money amount={sign ? sign * t.amount : t.amount} currency={t.currency ?? 'EUR'} signed={sign !== 0} />
          </p>
          <p className="detail__muted">{t.transaction_date ? dayLabel(t.transaction_date) : 'No date'} · {method}</p>
          {readOnly && <Badge tone="warn">Waiting to sync</Badge>}
        </header>

        <div className="ui-card detail__receipt">
          {t.receipt_path ? (
            <>
              {IMAGE.test(t.receipt_path)
                ? <img className="receipt-thumb" src={receiptUrl(t.id)} alt="" loading="lazy" />
                : <span className="receipt-thumb receipt-thumb--doc" aria-hidden="true">PDF</span>}
              <a className="detail__link" href={receiptUrl(t.id)} target="_blank" rel="noreferrer">View receipt</a>
            </>
          ) : (
            <>
              <button type="button" className="btn btn--ghost btn--sm" disabled={!online || readOnly || uploading}
                onClick={() => file.current?.click()}>
                {uploading ? 'Adding receipt…' : 'Add receipt'}
              </button>
              {!online && <span className="detail__muted">Needs a connection</span>}
              <input
                ref={file}
                type="file"
                hidden
                accept={RECEIPT_ACCEPT}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ''
                  if (f) void attach(f)
                }}
              />
            </>
          )}
        </div>

        <ul className="ui-list detail__fields">
          <FieldRow label="Category" value={n.category} onClick={() => setPicker('category')} disabled={readOnly} />
          <FieldRow label="Bucket" value={n.bucket} onClick={() => setPicker('bucket')} disabled={readOnly} />
          <FieldRow label="Paid by" value={n.payer} onClick={() => setPicker('payer')} disabled={readOnly} />
          <FieldRow label="Method" value={method} onClick={() => setPicker('method')} disabled={readOnly} />
          <FieldRow label="Notes" value={t.notes || 'None'} onClick={() => setPicker('notes')} disabled={readOnly} />
        </ul>

        {t.splits.length > 0 && <Shares t={t} refData={ref} />}

        <div className="ui-list detail__toggle">
          <ToggleRow label="Count in forecast" hint="Turn off for one-offs like a new fridge"
            checked={!t.exclude_from_forecast} disabled={readOnly}
            onChange={(on) => save({ exclude_from_forecast: !on })} />
        </div>

        {(linked || t.has_take) && (
          <section className="detail__section" aria-labelledby="linked-h">
            <h2 className="detail__h" id="linked-h">Linked</h2>
            <div className="ui-list">
              {linked && (
                <button type="button" className="ui-row" onClick={() => setEntryOpen(true)}>
                  <span className="ui-row__main">
                    <span className="ui-row__title">{linked.name}</span>
                    <span className="ui-row__sub">Due {dayLabel(linked.due_date)}</span>
                  </span>
                  <span className="field-row__chev" aria-hidden="true"><ChevronRightIcon /></span>
                </button>
              )}
              {t.has_take && <p className="ui-row">Cash was taken for it</p>}
            </div>
          </section>
        )}

        {!readOnly && (
          <HistoryList
            id={t.id}
            renderAction={(e) => e.kind === 'bulk_change' && e.can_undo && e.batch_id
              ? (
                <button type="button" className="btn btn--ghost btn--sm" disabled={!online || undoing !== null}
                  onClick={() => void undoOnce(e.batch_id!)}>
                  {undoing === e.batch_id ? 'Undoing…' : 'Undo this change'}
                </button>
              )
              : null}
          />
        )}

        {!readOnly && (
          <footer className="detail__footer">
            <button type="button" className="btn" onClick={() => navigate(`/new?from=${encodeURIComponent(t.id)}`)}>Copy as new</button>
            <button type="button" className="btn btn--danger" onClick={() => { deleteWithUndo(t); back() }}>Delete</button>
          </footer>
        )}
      </section>

      {ref && (
        <>
          <OptionSheet open={picker === 'category'} title="Category" value={t.category_id ?? ''}
            options={[{ value: '', label: 'None' }, ...ref.categories.map((c) => ({ value: c.id, label: c.name }))]}
            onPick={(v) => save({ category_id: v || null })} onClose={() => setPicker(null)} />
          <OptionSheet open={picker === 'bucket'} title="Bucket" value={t.bucket_id ?? ''} {...bucketOptions(t, ref)}
            onPick={(v) => save({ bucket_id: v || null })} onClose={() => setPicker(null)} />
          <OptionSheet open={picker === 'payer'} title="Paid by" value={t.payer_mode === 'own_share' ? OWN_SHARE : (t.paid_by ?? '')}
            options={payerOptions(ref)} onPick={(v) => save(payerPatch(v))} onClose={() => setPicker(null)} />
          <OptionSheet open={picker === 'method'} title="Method" value={t.payment_method}
            options={Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label }))}
            onPick={(v) => save({ payment_method: v })} onClose={() => setPicker(null)} />
        </>
      )}
      <NotesSheet open={picker === 'notes'} value={t.notes ?? ''} onSave={(v) => save({ notes: v || null })} onClose={() => setPicker(null)} />
      <EntrySheet entry={entryOpen && linked ? linked : null} onClose={() => setEntryOpen(false)} />
    </>
  )
}

export { Detail as ActivityDetail }
