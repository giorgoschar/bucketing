import { HBarList } from '../../../ui/charts'
import { Badge } from '../../../ui/Badge'
import { Money } from '../../../ui/Money'
import type { HouseholdMember } from '../../settings/hooks'
import { dayRange, eur } from '../format'
import { deltaText, paidOutSentence } from '../overview'
import { type Period, periodPhrase, previousPeriod } from '../period'
import type { InsightsData, PersonShare } from '../types'
import { Card } from './Card'

export function Identity({ member }: { member: HouseholdMember | undefined }) {
  const name = member?.display_name || member?.username || 'Member'
  return (
    <div className="insights__identity">
      <span className={member?.avatar_color ? 'avatar avatar--lg' : 'avatar avatar--lg avatar--fallback'}
        style={member?.avatar_color ? { background: member.avatar_color } : undefined} aria-hidden="true">
        {name.slice(0, 1).toUpperCase()}
      </span>
      <span className="insights__identity-text">Viewing <strong>{name}</strong>’s share</span>
    </div>
  )
}

export function Headline({ data }: { data: InsightsData }) {
  const delta = deltaText(data.kpis.change_pct)
  const up = (data.kpis.change_pct ?? 0) > 0
  return (
    <div className="insights__headline">
      <p className="ui-eyebrow insights__eyebrow">Spent · {dayRange(data.start_date, data.end_date)}</p>
      <p className="insights__big"><Money amount={data.total_spent} className="ui-figure" /></p>
      {delta && <Badge tone={up ? 'warn' : 'pos'}>{delta}</Badge>}
    </div>
  )
}

export function ShareCard({ query, who, period }: {
  query: { data?: PersonShare | null; isError: boolean; refetch(): unknown }
  who: { me: boolean; name: string }
  period: Period
}) {
  if (query.data === undefined || query.data === null) {
    return (
      <Card title="Paid out vs share">
        {query.isError ? (
          <p className="insights__error">
            <span>Couldn't load this</span>
            <button type="button" className="btn btn--sm" onClick={() => void query.refetch()}>Retry</button>
          </p>
        ) : (
          <div className="ui-skeleton" role="status" aria-busy="true" aria-label="Loading" />
        )}
      </Card>
    )
  }
  const s = query.data
  return (
    <Card title="Paid out vs share">
      <HBarList
        label="Paid out and share"
        format={eur}
        rows={[
          { id: 'paid', label: 'Paid out', value: s.paid_out },
          { id: 'share', label: who.me ? 'Your share' : 'Their share', value: s.my_share },
        ]}
      />
      <p className="insights__sentence">{paidOutSentence(s.balance, who, periodPhrase(period))}</p>
    </Card>
  )
}

export function EmptyPeriod({ data, period, onPeriod }: { data: InsightsData; period: Period; onPeriod(p: Period): void }) {
  const prev = (data.kpis.previous_total ?? 0) > 0 ? previousPeriod(period, data.kpis.range_start, data.kpis.range_end) : null
  return (
    <Card title="No spending in this period">
      {prev && <button type="button" className="btn btn--sm insights__prev" onClick={() => onPeriod(prev)}>See the previous period</button>}
    </Card>
  )
}
