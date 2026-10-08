import type { MonthPictureOut } from '../../data/types'
import { TopBar } from '../../shell/TopBar'
import { formatMonthName, todayISO } from '../../ui/format'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { usePendingTransactions } from '../composer/hooks/usePendingTransactions'
import { usePlanMonth } from '../plan/hooks'
import { NeedsAttention } from './NeedsAttention'
import { RecentActivity } from './RecentActivity'
import './home.css'

export function Home() {
  const picture = usePlanMonth(todayISO().slice(0, 7))
  return (
    <>
      <TopBar title="Home" />
      <section className="screen home">
        <QueryView result={picture} noDataText="No saved data yet. Connect once to load Home.">
          {(p) => <HomeFigure picture={p} />}
        </QueryView>
        <WaitingToSync />
        <NeedsAttention />
        <RecentActivity />
      </section>
    </>
  )
}

function HomeFigure({ picture: p }: { picture: MonthPictureOut }) {
  const outSoFar = p.fixed.so_far + p.buckets.so_far
  return (
    <div className="ui-hero home-hero">
      <p className="ui-eyebrow home-hero__eyebrow">{formatMonthName(Number(p.month.slice(5, 7)))} · projected</p>
      <Money className="ui-figure home-hero__figure" amount={p.net_projected} signed estimated={p.estimated} />
      <p className="home-hero__sub">
        In <Money amount={p.income.so_far} /> so far · Out <Money amount={outSoFar} /> so far
      </p>
    </div>
  )
}

/** Queued saves are not in the header figure (2b spec §5.3); say how many are waiting instead. */
function WaitingToSync() {
  const n = usePendingTransactions().waitingCount
  if (n === 0) return null
  return <p className="home__waiting">{n === 1 ? '1 entry waiting to sync' : `${n} entries waiting to sync`}</p>
}
