import { type ReactNode, useId, useState } from 'react'
import { Link, useParams } from 'react-router'
import { memberName, useHousehold } from '../../../data/reads'
import { useOnline } from '../../../data/online'
import { useSession } from '../../../session/SessionProvider'
import { BackHeader } from '../../../ui/BackHeader'
import { EmptyState } from '../../../ui/EmptyState'
import { Money } from '../../../ui/Money'
import { QueryView } from '../../../ui/QueryView'
import { formatShortDate } from '../../../ui/format'
import { changeBody, changeLabel, changeTitle } from '../bills/format'
import { EntrySheet } from '../../plan/EntrySheet'
import { eur, signedEur } from '../format'
import { isMonth, useEntriesOn, useMarkReviewed, useStatement } from './hooks'
import { OfflineNote } from './OfflineNote'
import {
  comparison, doneNote, LIVE_NOTE, monthBounds, monthTitle, ofBudget, overText, short, stateLine, usuallyText, type ReviewedBy,
} from './sentences'
import type { PlannedSide, StatementOut } from './types'
import '../insights.css'
import '../bills/bills.css'
import './statements.css'

/** The route element: /insights/statements/:month. */
export function Statement() {
  const { month = '' } = useParams()
  return <StatementView month={month} />
}

/** One past month, live (spec §4.2). The month in review and every older one are the same page. */
export function StatementView({ month }: { month: string }) {
  const result = useStatement(month)
  // A malformed month is never asked for; a month the server refuses (400, 404) comes back as null.
  if (!isMonth(month) || result.data === null) {
    return (
      <>
        <BackHeader title="Statement" back="/insights/statements" />
        <section className="screen insights stmt">
          <EmptyState title="No statement for this month yet." action={{ label: 'All statements', to: '/insights/statements' }} />
        </section>
      </>
    )
  }
  return (
    <>
      <BackHeader title={result.data?.label ?? monthTitle(month)} back="/insights/statements" />
      <section className="screen insights stmt stmtpage">
        <QueryView result={result} showBanner={false} noDataText="No saved statement yet. Connect once to load it.">
          {(s) => (
            <>
              {result.stale && <Cell wide><OfflineNote /></Cell>}
              {s && <Body s={s} />}
            </>
          )}
        </QueryView>
      </section>
    </>
  )
}

/** One direct child of the page: on the desktop the cells flow down two columns, wide ones across. */
function Cell({ wide = false, children }: { wide?: boolean; children: ReactNode }) {
  return <div className={wide ? 'stmtcell stmtcell--wide' : 'stmtcell'}>{children}</div>
}

function Sec({ title, wide = false, children }: { title: string; wide?: boolean; children: ReactNode }) {
  const id = useId()
  return (
    <Cell wide={wide}>
      <section className="ui-card insights__card stmtsec" aria-labelledby={id}>
        <h2 id={id} className="insights__cardtitle">{title}</h2>
        {children}
      </section>
    </Cell>
  )
}

/** A sentence with its amounts in `ui-num`, so they keep their figures and the sentence still wraps (§5). */
function Nums({ text }: { text: string }) {
  return <>{text.split(/([−-]?€[\d,]+(?:\.\d{2})?)/).map((part, i) => (i % 2 ? <span key={i} className="ui-num stmtnum">{part}</span> : part))}</>
}

const Quiet = ({ children }: { children: string }) => <p className="insights__note">{children}</p>

function Body({ s }: { s: StatementOut }) {
  const { me } = useSession()
  const members = useHousehold().data?.members
  const who = members?.find((m) => m.user_id === s.reviewed_by)
  // "by you" from the id; otherwise the household's name for them, then the server's (a member who has left).
  const name = who ? memberName(who) : s.reviewed_by_name
  const by: ReviewedBy = s.reviewed_by && s.reviewed_by === me?.id ? { kind: 'you' } : name ? { kind: 'name', name } : { kind: 'none' }
  return (
    <>
      <Cell wide>
        <div className="stmthead">
          <p className="stmthead__state">{stateLine(s, by)}</p>
          <p className="insights__note">{LIVE_NOTE}</p>
        </div>
      </Cell>
      <Totals s={s} />
      <Planned s={s} />
      <Budgets s={s} />
      <Bills s={s} />
      <Cash s={s} meId={me?.id} />
      <Categories s={s} />
      <Biggest s={s} />
      <Done s={s} />
    </>
  )
}

function Totals({ s }: { s: StatementOut }) {
  const { totals: t } = s
  const prev = t.previous
  const tile = (label: string, value: string, cur: number, before: number | undefined) => (
    <div className="stmttile">
      <dt>{label}</dt>
      <dd className="ui-num stmttile__value">{value}</dd>
      {prev && before !== undefined && <dd className="stmttile__cmp"><Nums text={comparison(cur, before, prev.month)} /></dd>}
    </div>
  )
  return (
    <Sec title="In, out and net" wide>
      <dl className="stmttiles">
        {tile('In', eur(t.in), t.in, prev?.in)}
        {tile('Out', eur(t.out), t.out, prev?.out)}
        {tile('Net', signedEur(t.net), t.net, prev?.net)}
      </dl>
    </Sec>
  )
}

function Planned({ s }: { s: StatementOut }) {
  const [picked, setPicked] = useState<{ id: string; date: string } | null>(null)
  const day = useEntriesOn(picked?.date ?? null).data
  const entry = picked ? day?.find((e) => e.id === picked.id) ?? null : null
  const row = (label: string, p: PlannedSide) => (
    <tr>
      <th scope="row">{label}</th>
      <td className="ui-num">{eur(p.planned)}</td>
      <td className="ui-num">{eur(p.actual)}</td>
      <td className="ui-num">{signedEur(Math.round((p.actual - p.planned) * 100) / 100)}</td>
    </tr>
  )
  const { open } = s.planned
  return (
    <Sec title="Planned vs actual" wide>
      <div className="stmtscroll">
        <table className="stmttable">
          <thead>
            <tr><th scope="col"><span className="ui-sr">Direction</span></th><th scope="col">Planned</th><th scope="col">Actual</th><th scope="col">Difference</th></tr>
          </thead>
          <tbody>{row('In', s.planned.in)}{row('Out', s.planned.out)}</tbody>
        </table>
      </div>
      {open.length === 0 ? (
        <Quiet>Everything planned was done or skipped.</Quiet>
      ) : (
        <>
          <h3 className="stmtsub">Still open</h3>
          <ul className="stmtlist">
            {open.map((o) => (
              <li key={o.entry_id}>
                <button type="button" className="stmtitem stmtitem--btn" onClick={() => setPicked({ id: o.entry_id, date: o.due_date })}>
                  <span className="stmtitem__main">
                    <span className="stmtitem__name">{o.name}</span>
                    <span className="stmtitem__sub">{formatShortDate(o.due_date)}</span>
                  </span>
                  <Money amount={o.amount} estimated={o.estimated} nullText="No amount" className="stmtitem__amount" />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <EntrySheet entry={entry} onClose={() => setPicked(null)} />
    </Sec>
  )
}

function Budgets({ s }: { s: StatementOut }) {
  return (
    <Sec title="Budgets that ran over">
      {s.budgets_over.length === 0 ? <Quiet>No budget ran over.</Quiet> : (
        <ul className="stmtlist">
          {s.budgets_over.map((b) => (
            <li key={b.bucket_id} className="stmtitem">
              <span className="stmtitem__main">
                <span className="stmtitem__name">{b.name}</span>
                <span className="stmtitem__sub"><Nums text={ofBudget(b.spent, b.budget)} /></span>
              </span>
              <span className="stmtitem__flag"><Nums text={overText(b.over)} /></span>
            </li>
          ))}
        </ul>
      )}
    </Sec>
  )
}

function Bills({ s }: { s: StatementOut }) {
  return (
    <Sec title="Bills that changed">
      {s.bills_changed.length === 0 ? <Quiet>No bill changed much.</Quiet> : (
        <ul className="stmtlist">
          {s.bills_changed.map((b) => {
            const c = { ...b, delta: Math.round((b.amount - b.usual) * 100) / 100 }
            return (
              <li key={b.entry_id}>
                <Link className="stmtitem stmtitem--link" to={`/insights/bills/${encodeURIComponent(b.item_id)}`}>
                  <span className="stmtitem__main">
                    <span className="stmtitem__name stmtitem__name--wrap"><Nums text={changeTitle(b.name, c)} /></span>
                    <span className="stmtitem__sub">{formatShortDate(b.due_date)} · <Nums text={changeBody(c, null)} /></span>
                    <span className={`billrow__change billrow__change--${b.direction}`}>{changeLabel(c)}</span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Sec>
  )
}

function Cash({ s, meId }: { s: StatementOut; meId: string | undefined }) {
  return (
    <Sec title="Cash not logged">
      {s.cash.length === 0 ? <Quiet>All cash is logged.</Quiet> : (
        <ul className="stmtlist">
          {s.cash.map((c) => (
            <li key={c.member_id} className="stmtitem">
              <span className="stmtitem__main">
                <span className="stmtitem__name">{c.name}</span>
              </span>
              <span className="ui-num stmtitem__amount">{short(c.not_yet_logged)}</span>
              {c.member_id === meId && Number.isFinite(c.not_yet_logged) && (
                <Link className="btn btn--sm btn--primary" to={`/new?mode=cash&take=none&amount=${c.not_yet_logged.toFixed(2)}`}>Log it</Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Sec>
  )
}

function Categories({ s }: { s: StatementOut }) {
  const { from, to } = monthBounds(s.month)
  return (
    <Sec title="Categories above usual">
      {s.categories_over.length === 0 ? <Quiet>Nothing above its usual.</Quiet> : (
        <ul className="stmtlist">
          {s.categories_over.map((c) => {
            const inner = (
              <>
                <span className="stmtitem__icon" aria-hidden="true">{c.icon}</span>
                <span className="stmtitem__main">
                  <span className="stmtitem__name">{c.name}</span>
                  {usuallyText(c.usual) && <span className="stmtitem__sub"><Nums text={usuallyText(c.usual) ?? ''} /></span>}
                </span>
                <span className="ui-num stmtitem__amount">{short(c.amount)}</span>
              </>
            )
            return (
              <li key={c.category_id ?? c.name}>
                {c.category_id
                  ? <Link className="stmtitem stmtitem--link" to={`/insights/category/${encodeURIComponent(c.category_id)}?p=custom&from=${from}&to=${to}`}>{inner}</Link>
                  : <div className="stmtitem">{inner}</div>}
              </li>
            )
          })}
        </ul>
      )}
    </Sec>
  )
}

function Biggest({ s }: { s: StatementOut }) {
  return (
    <Sec title="Biggest expenses">
      {s.biggest.length === 0 ? <Quiet>No expenses this month.</Quiet> : (
        <ul className="stmtlist">
          {s.biggest.map((b) => (
            <li key={b.transaction_id}>
              <Link className="stmtitem stmtitem--link" to={`/activity/${encodeURIComponent(b.transaction_id)}`}>
                <span className="stmtitem__main">
                  <span className="stmtitem__name">{b.label}</span>
                  <span className="stmtitem__sub">{formatShortDate(b.date)}{b.category ? ` · ${b.category}` : ''}</span>
                </span>
                <Money amount={b.amount} className="stmtitem__amount" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Sec>
  )
}

/** Only in the review window and before anyone pressed Done (spec §4.2). */
function Done({ s }: { s: StatementOut }) {
  const online = useOnline()
  const mark = useMarkReviewed(s.month)
  const [busy, setBusy] = useState(false)
  if (s.closed || s.reviewed_at) return null
  const press = async () => {
    setBusy(true)
    try { await mark() } finally { setBusy(false) }
  }
  return (
    <Cell wide>
      <div className="stmtdone">
        <button type="button" className="btn btn--primary btn--block" disabled={!online || busy} onClick={() => void press()}>Done</button>
        <p className="insights__note">{online ? doneNote(s.month) : 'Connect to finish the review'}</p>
      </div>
    </Cell>
  )
}
