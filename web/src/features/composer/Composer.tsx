import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { ComposerForm } from './ComposerForm'
import { todayLocal } from './dates'
import { type DefaultsRecord, initialNew } from './defaults'
import { copyOf, fromTransaction } from './model'
import type { ComposerState } from './state'
import { useClose } from './useClose'
import { type ComposerData, useComposerData, useTransaction } from './hooks/useComposerData'
import { useDefaults } from './hooks/useDefaults'
import './composer.css'

export function Composer() {
  const data = useComposerData()
  const defaults = useDefaults(data.hh)
  const [params] = useSearchParams()
  const { id } = useParams()
  if (!data.ready || !defaults) return <ComposerSkeleton />
  // Keyed by id: moving from one entry to another starts that entry's form afresh.
  if (id) return <EditLoader key={`edit:${id}`} id={id} copy={false} data={data} defaults={defaults} />
  const from = params.get('from')
  if (from) return <EditLoader key={`copy:${from}`} id={from} copy data={data} defaults={defaults} />
  return <NewComposer data={data} defaults={defaults} cash={params.get('mode') === 'cash'} />
}

export function ComposerSkeleton() {
  return <div className="composer composer--loading" aria-busy="true" aria-label="Loading" />
}

function NewComposer({ data, defaults, cash }: { data: ComposerData; defaults: DefaultsRecord; cash: boolean }) {
  // One client_id per composer mount (spec §5.1).
  const [initial] = useState(() =>
    initialNew({
      defaults, buckets: data.buckets, categories: data.categories, memberIds: data.members.map((m) => m.user_id),
      meId: data.meId, householdCurrency: data.householdCurrency, type: 'expense', today: todayLocal(),
      clientId: crypto.randomUUID(), cash,
    }),
  )
  return <ComposerForm initial={initial} data={data} defaults={defaults} />
}

function EditLoader({ id, copy, data, defaults }: { id: string; copy: boolean; data: ComposerData; defaults: DefaultsRecord }) {
  const { txn, status } = useTransaction(id)
  const [initial, setInitial] = useState<ComposerState | null>(null)
  // Initialise once: a background refetch must not wipe what the user is typing.
  if (txn && initial === null) {
    const loaded = fromTransaction(txn, { householdCurrency: data.householdCurrency, meId: data.meId })
    setInitial(copy ? copyOf(loaded, { clientId: crypto.randomUUID(), today: todayLocal() }) : loaded)
  }
  if (initial) return <ComposerForm initial={initial} data={data} defaults={defaults} />
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
