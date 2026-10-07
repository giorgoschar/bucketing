import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { ComposerForm } from './ComposerForm'
import { todayLocal } from './dates'
import { type DefaultsRecord, initialNew } from './defaults'
import { type ComposerData, useComposerData } from './hooks/useComposerData'
import { useDefaults } from './hooks/useDefaults'
import './composer.css'

export function Composer() {
  const data = useComposerData()
  const defaults = useDefaults(data.hh)
  const [params] = useSearchParams()
  if (!data.ready || !defaults) return <ComposerSkeleton />
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
