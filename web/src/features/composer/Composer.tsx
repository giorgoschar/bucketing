import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { ComposerForm } from './ComposerForm'
import { todayLocal } from './dates'
import { type DefaultsRecord, initialNew } from './defaults'
import { copyOf, fromTransaction } from './model'
import { draftKey } from './draft'
import { usePanel } from './panel'
import type { ComposerState } from './state'
import { useClose } from './useClose'
import { type ComposerData, useComposerData, useTransaction } from './hooks/useComposerData'
import { useDefaults } from './hooks/useDefaults'
import './composer.css'

export function Composer() {
  const data = useComposerData()
  const defaults = useDefaults(data.hh)
  const [params] = useSearchParams()
  const route = useParams()
  // In the side panel the entry is `?edit=<id>`; the router's :id belongs to the screen behind it.
  const panel = usePanel()
  const id = panel ? panel.editId : route.id
  // The panel lives on another screen's address, where ?from= can mean something else (Insights' period).
  const from = panel ? params.get('copy') : params.get('from')
  if (!data.ready || !defaults) return <ComposerSkeleton />
  const dk = draftKey(id, id ? null : from)
  // Keyed by id: moving from one entry to another starts that entry's form afresh.
  if (id) return <EditLoader key={`edit:${id}`} id={id} copy={false} data={data} defaults={defaults} dk={dk} />
  if (from) return <EditLoader key={`copy:${from}`} id={from} copy data={data} defaults={defaults} dk={dk} />
  return (
    <NewComposer data={data} defaults={defaults} cash={params.get('mode') === 'cash'}
      amount={params.get('amount')} take={params.get('take')} dk={dk} />
  )
}

export function ComposerSkeleton() {
  return <div className="composer composer--loading" aria-busy="true" aria-label="Loading" />
}

interface NewProps { data: ComposerData; defaults: DefaultsRecord; cash: boolean; amount: string | null; take: string | null; dk: string }

function NewComposer({ data, defaults, cash, amount, take, dk }: NewProps) {
  // One client_id per composer mount (spec §5.1).
  const [initial] = useState(() =>
    initialNew({
      defaults, buckets: data.buckets, categories: data.categories, memberIds: data.members.map((m) => m.user_id),
      meId: data.meId, householdCurrency: data.householdCurrency, type: 'expense', today: todayLocal(),
      clientId: crypto.randomUUID(), cash, amount, take,
    }),
  )
  return <ComposerForm initial={initial} data={data} defaults={defaults} draftKey={dk} />
}

function EditLoader({ id, copy, data, defaults, dk }: { id: string; copy: boolean; data: ComposerData; defaults: DefaultsRecord; dk: string }) {
  const { txn, status } = useTransaction(id)
  const [initial, setInitial] = useState<ComposerState | null>(null)
  // Initialise once: a background refetch must not wipe what the user is typing.
  if (txn && initial === null) {
    const loaded = fromTransaction(txn, { householdCurrency: data.householdCurrency, meId: data.meId })
    setInitial(copy ? copyOf(loaded, { clientId: crypto.randomUUID(), today: todayLocal() }) : loaded)
  }
  if (initial) return <ComposerForm initial={initial} data={data} defaults={defaults} draftKey={dk} />
  if (status === 'missing') return <Gone text="This entry no longer exists" />
  if (status === 'offline') return <Gone text="Connect once to load this entry." />
  return <ComposerSkeleton />
}

function Gone({ text }: { text: string }) {
  const close = useClose()
  return (
    <div className="composer composer--gone">
      <p role="alert" className="composer__gone">{text}</p>
      <button type="button" className="btn btn--lg btn--block" onClick={close}>Back</button>
    </div>
  )
}
