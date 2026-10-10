import { Link } from 'react-router'
import { BackHeader } from '../../../ui/BackHeader'
import { EmptyState } from '../../../ui/EmptyState'
import { QueryView } from '../../../ui/QueryView'
import { eur, signedEur } from '../format'
import { useStatements } from './hooks'
import { OfflineNote } from './OfflineNote'
import type { StatementListMonth, StatementReview } from './types'
import '../insights.css'
import './statements.css'

/** /insights/statements: every past month, newest first; the month in review leads (spec §4.3). */
export function StatementsList() {
  const list = useStatements()
  return (
    <>
      <BackHeader title="Statements" back="/insights" />
      <section className="screen insights stmt">
        <QueryView result={list} showBanner={false} noDataText="No saved statements yet. Connect once to load them.">
          {({ review, months }) => {
            const rows = review ? [...months.filter((m) => m.month === review.month), ...months.filter((m) => m.month !== review.month)] : months
            return (
              <>
                {list.stale && <OfflineNote />}
                {rows.length === 0 ? (
                  <EmptyState title="No past months yet." />
                ) : (
                  <div className="ui-card stmt__group">
                    {rows.map((m) => <MonthRow key={m.month} m={m} review={review?.month === m.month ? review : null} />)}
                  </div>
                )}
              </>
            )
          }}
        </QueryView>
      </section>
    </>
  )
}

function MonthRow({ m, review }: { m: StatementListMonth; review: StatementReview | null }) {
  const mark = review ? null : m.reviewed_at ? 'Reviewed' : !m.closed ? 'Open for review' : null
  return (
    <Link className="stmtrow" to={`/insights/statements/${encodeURIComponent(m.month)}`}>
      <span className="stmtrow__head">
        <span className="stmtrow__name">{m.label}</span>
        {review && (
          <span className="stmtrow__review"><span className="stmtrow__cta">Review</span></span>
        )}
        {mark && <span className={`stmtrow__mark${m.reviewed_at ? ' stmtrow__mark--done' : ''}`}>{mark}</span>}
      </span>
      <dl className="stmtrow__trio">
        <div><dt>In</dt><dd className="ui-num">{eur(m.in)}</dd></div>
        <div><dt>Out</dt><dd className="ui-num">{eur(m.out)}</dd></div>
        <div><dt>Net</dt><dd className="ui-num">{signedEur(m.net)}</dd></div>
      </dl>
    </Link>
  )
}
