import type { ReactNode } from 'react'
import { useSession } from '../../session/SessionProvider'
import { TopBar } from '../../shell/TopBar'
import { Chips } from '../../ui/Chips'
import { QueryView } from '../../ui/QueryView'
import type { HouseholdMember } from '../settings/hooks'
import { LensControl } from './LensControl'
import { useInsights, useMembers, usePersonShare } from './hooks'
import { HOUSEHOLD, type Lens, lensOptions, useLens } from './lens'
import { type WidgetId, visibleWidgets } from './overview'
import { type Period, type Preset, PRESETS, usePeriod } from './period'
import { type InsightsData, NO_FILTERS } from './types'
import { EmptyPeriod, Headline, Identity, ShareCard } from './widgets/summary'
import './insights.css'

export interface WidgetCtx {
  data: InsightsData
  period: Period
  lens: Lens
  members: HouseholdMember[]
  meId: string
  setPeriod(p: Period): void
}

// F2.2 replaces the `() => null` entries.
const RENDER: Record<Exclude<WidgetId, 'identity' | 'share'>, (ctx: WidgetCtx) => ReactNode> = {
  headline: ({ data }) => <Headline data={data} />,
  empty: ({ data, period, setPeriod }) => <EmptyPeriod data={data} period={period} onPeriod={setPeriod} />,
  onTrack: () => null,
  inOut: () => null,
  where: () => null,
  inOutMonths: () => null,
  trend: () => null,
  biggest: () => null,
  method: () => null,
  budgets: () => null,
  savings: () => null,
  vsUsual: () => null,
  fuel: () => null,
}

export function Insights() {
  const { me } = useSession()
  const household = useMembers()
  const members = household.data?.members
  const [period, setPeriod] = usePeriod()
  const [lens, setLens] = useLens(members)
  const filters = NO_FILTERS // F2.3 wires the Filters sheet
  const insights = useInsights(period, lens, filters)
  const share = usePersonShare(period, lens === HOUSEHOLD ? null : lens)
  const meId = me?.id ?? ''
  const member = members?.find((m) => m.user_id === lens)
  const firstView = period.preset === 'this_month' && lens === HOUSEHOLD

  const pickPreset = (p: Preset) => {
    if (p !== 'custom') setPeriod({ preset: p })
  }

  return (
    <>
      <TopBar title="Insights" />
      <div className="insights__bar">
        <Chips label="Period" options={PRESETS} value={period.preset} onChange={pickPreset} />
      </div>
      <section className="screen insights">
        {members && meId && members.length > 1 && (
          <LensControl label="Whose spending" options={lensOptions(members, meId)} value={lens} onChange={setLens} />
        )}
        <QueryView
          result={insights}
          noDataText={firstView ? 'No saved data yet. Connect once to load Insights.' : 'No saved data for this view. Connect once to load it.'}
        >
          {(data) => {
            const ctx: WidgetCtx = { data, period, lens, members: members ?? [], meId, setPeriod }
            return visibleWidgets(data, { lens, period }).map((id) => (
              <div key={id} data-widget={id} className="insights__widget">
                {id === 'identity' ? (
                  <Identity member={member} />
                ) : id === 'share' ? (
                  <ShareCard query={share} period={period} who={{ me: lens === meId, name: (member?.display_name || member?.username || '').split(' ')[0] }} />
                ) : (
                  RENDER[id](ctx)
                )}
              </div>
            ))
          }}
        </QueryView>
      </section>
    </>
  )
}
