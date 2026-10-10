import { lazy, type ReactNode, Suspense, useState } from 'react'
import { useSession } from '../../session/SessionProvider'
import { useIsDesktop } from '../../ui/useIsDesktop'
import { TopBar } from '../../shell/TopBar'
import { Chips } from '../../ui/Chips'
import { QueryView } from '../../ui/QueryView'
import type { HouseholdMember } from '../settings/hooks'
import { useInsightFilters } from './filters'
import { FiltersIcon } from './icons'
import { LensControl } from './LensControl'
import { RangeSheet } from './RangeSheet'
import { useInsights, useMembers, usePersonShare } from './hooks'
import { HOUSEHOLD, type Lens, lensOptions, useLens } from './lens'
import { type WidgetId, visibleWidgets } from './overview'
import { type Period, type Preset, PRESETS, usePeriod } from './period'
import { type InsightFilters, type InsightsData, NO_FILTERS } from './types'
import {
  Biggest, BillsCard, BudgetsCard, FuelCard, HowYouPaid, InOut, InOutMonths, OnTrack, SavingsRate, SpendTrend, VsUsual, WhereItWent,
} from './widgets/cards'
import { EmptyPeriod, Headline, Identity, ShareCard } from './widgets/summary'
import './insights.css'

// Desktop only (spec §5.4): kept out of the phone's main chunk.
const BillsPanel = lazy(() => import('./desktop/DesktopPanels').then((m) => ({ default: m.BillsPanel })))
const MonthsTable = lazy(() => import('./desktop/DesktopPanels').then((m) => ({ default: m.MonthsTable })))
const CategoriesTable = lazy(() => import('./desktop/DesktopPanels').then((m) => ({ default: m.CategoriesTable })))

export interface WidgetCtx {
  data: InsightsData
  period: Period
  lens: Lens
  members: HouseholdMember[]
  meId: string
  filters?: InsightFilters
  setPeriod(p: Period): void
}

const RENDER: Record<Exclude<WidgetId, 'identity' | 'share'>, (ctx: WidgetCtx) => ReactNode> = {
  headline: ({ data }) => <Headline data={data} />,
  empty: ({ data, period, setPeriod }) => <EmptyPeriod data={data} period={period} onPeriod={setPeriod} />,
  onTrack: (c) => <OnTrack {...c} />,
  inOut: (c) => <InOut {...c} />,
  where: (c) => <WhereItWent {...c} />,
  inOutMonths: (c) => <InOutMonths {...c} />,
  trend: (c) => <SpendTrend {...c} />,
  biggest: (c) => <Biggest {...c} />,
  method: (c) => <HowYouPaid {...c} />,
  budgets: (c) => <BudgetsCard {...c} />,
  savings: (c) => <SavingsRate {...c} />,
  vsUsual: (c) => <VsUsual {...c} />,
  bills: () => <BillsCard />,
  billsPanel: () => <Suspense fallback={null}><BillsPanel /></Suspense>,
  monthsTable: (c) => <Suspense fallback={null}><MonthsTable period={c.period} lens={c.lens} filters={c.filters ?? NO_FILTERS} /></Suspense>,
  categoriesTable: (c) => <Suspense fallback={null}><CategoriesTable data={c.data} period={c.period} lens={c.lens} /></Suspense>,
  fuel: (c) => <FuelCard {...c} />,
}

export function Insights() {
  const { me } = useSession()
  const household = useMembers()
  const members = household.data?.members
  const [period, setPeriod] = usePeriod()
  const [lens, setLens] = useLens(members)
  const [filters, setFilters] = useInsightFilters()
  const [sheet, setSheet] = useState(false)
  const insights = useInsights(period, lens, filters)
  const share = usePersonShare(period, lens === HOUSEHOLD ? null : lens)
  const meId = me?.id ?? ''
  const member = members?.find((m) => m.user_id === lens)
  const desktop = useIsDesktop()
  const firstView = period.preset === 'this_month' && lens === HOUSEHOLD

  const pickPreset = (p: Preset) => {
    if (p === 'custom') setSheet(true)
    else setPeriod({ preset: p })
  }
  const active = filters.bucketIds.length + filters.categoryIds.length
  const lensControl = members && meId && (
    <LensControl label="Whose spending" options={lensOptions(members, meId)} value={lens} onChange={setLens} />
  )

  return (
    <>
      <TopBar
        title="Insights"
        actions={
          <button type="button" className="ui-iconbtn ui-iconbtn--bare insights__filters" aria-label="Filters"
            aria-haspopup="dialog" onClick={() => setSheet(true)}>
            <FiltersIcon />
            {active > 0 && <span className="insights__filtercount" aria-hidden="true">{active}</span>}
          </button>
        }
      />
      <div className="insights__bar insights__bar--wide">
        <Chips label="Period" options={PRESETS} value={period.preset} onChange={pickPreset} />
        {/* Desktop: the lens joins the period controls in one row (spec §5.4). */}
        {desktop && lensControl}
      </div>
      <section className="screen insights shell__main--wide">
        {!desktop && lensControl}
        <QueryView
          result={insights}
          noDataText={firstView ? 'No saved data yet. Connect once to load Insights.' : 'No saved data for this view. Connect once to load it.'}
        >
          {(data) => {
            const ctx: WidgetCtx = { data, period, lens, members: members ?? [], meId, filters, setPeriod }
            return visibleWidgets(data, { lens, period, bills: true, desktop }).map((id) => (
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
      <RangeSheet
        open={sheet}
        onClose={() => setSheet(false)}
        initialFrom={period.from ?? insights.data?.kpis.range_start ?? ''}
        initialTo={period.to ?? insights.data?.kpis.range_end ?? ''}
        filters={filters}
        onApply={(p, f) => { setPeriod(p); setFilters(f); setSheet(false) }}
        onReset={() => { setPeriod({ preset: 'this_month' }); setFilters(NO_FILTERS); setSheet(false) }}
      />
    </>
  )
}
