import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import type { EntryOut, MatchOut } from '../../data/types'
import { dismissFailed } from '../../offline/useQueue'
import { Badge } from '../../ui/Badge'
import { formatMoney, formatMonthName, formatShortDate } from '../../ui/format'
import { AlertIcon, CheckIcon, ClockIcon, LinkIcon, WalletIcon, XIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { EntrySheet, type EntryIntent } from '../plan/EntrySheet'
import { changeTitle, moneyShort } from '../insights/bills/format'
import { visibleAttention, type AttentionItem } from './attention'
import { setAttentionExpanded, useAttentionExpanded } from './attentionExpanded'
import { dismissBill } from './billDismiss'
import { useAttention, useMatchActions } from './hooks'
import './home.css'

export function NeedsAttention() {
  const { items, ready } = useAttention()
  const [open, setOpen] = useState<{ entry: EntryOut; intent: EntryIntent } | null>(null)
  const expanded = useAttentionExpanded()
  if (!ready && items.length === 0) return null
  const { shown, hidden } = visibleAttention(items, expanded)
  const onOpen = (entry: EntryOut, intent: EntryIntent) => setOpen({ entry, intent })
  return (
    <section className="home-attn" aria-labelledby="attn-title">
      <div className="ui-sec">
        <h2 id="attn-title" className="ui-sec__title">
          Needs attention{items.length > 0 && <Badge tone="neg">{items.length}</Badge>}
        </h2>
      </div>
      {items.length === 0 ? (
        <div className="ui-card home-clear"><CheckIcon /> All clear</div>
      ) : (
        <>
          <div className="ui-list" id="attn-list">
            {shown.map((it, n) => (
              <div key={it.key} className="home-attn__wrap" data-attn={it.kind}>
                <AttentionRow item={it} lead={n === 0} onOpen={onOpen} />
                {it.also && (
                  <ul className="home-attn__also">
                    {it.also.map((a) => <AlsoLine key={a.key} line={a} onOpen={onOpen} />)}
                  </ul>
                )}
              </div>
            ))}
          </div>
          {hidden > 0 && (
            <button type="button" className="btn btn--sm btn--ghost home-attn__more" aria-expanded={expanded} aria-controls="attn-list"
              onClick={() => setAttentionExpanded(!expanded)}>
              {expanded ? 'Show fewer' : `Show ${hidden} more`}
            </button>
          )}
        </>
      )}
      <EntrySheet entry={open?.entry ?? null} intent={open?.intent} onClose={() => setOpen(null)} />
    </section>
  )
}

type Open = (e: EntryOut, intent: EntryIntent) => void

/** A merged line under a row (spec §2.1): itself a link. Dismissing a bill change removes only this line. */
function AlsoLine({ line, onOpen }: { line: AttentionItem; onOpen: Open }) {
  switch (line.kind) {
    case 'overdue':
      return <li><button type="button" className="home-attn__link" onClick={() => onOpen(line.entry, 'default')}>Was due {formatShortDate(line.entry.due_date)}</button></li>
    case 'missingAmount':
      return <li><button type="button" className="home-attn__link" onClick={() => onOpen(line.entry, 'amount')}>Needs an amount for {formatShortDate(line.entry.due_date)}</button></li>
    case 'billChange': {
      const c = line.bill.change
      if (!c) return null
      return (
        <li className="home-attn__alsoRow">
          <Link className="home-attn__link" to={`/insights/bills/${encodeURIComponent(line.bill.item_id)}`}>
            Was {moneyShort(c.amount)}, usually {moneyShort(c.usual)}
          </Link>
          <button type="button" className="ui-iconbtn ui-iconbtn--bare home-attn__x" aria-label={`Dismiss ${line.bill.name}`}
            onClick={() => dismissBill(c.entry_id)}><XIcon /></button>
        </li>
      )
    }
    default:
      return null
  }
}

/** A row's action is a quiet text button, filled only on the first row. */
const act = (lead: boolean) => (lead ? 'btn btn--sm btn--primary' : 'btn btn--sm btn--ghost')

function LinkRow({ to, leading, title, subtitle, badges }: { to: string; leading?: ReactNode; title: ReactNode; subtitle?: ReactNode; badges?: ReactNode }) {
  return (
    <Link to={to} className="ui-row">
      {leading && <span className="ui-row__lead">{leading}</span>}
      <span className="ui-row__main">
        <span className="ui-row__title">{title}</span>
        {subtitle && <span className="ui-row__sub">{subtitle}</span>}
        {badges && <span className="ui-row__badges">{badges}</span>}
      </span>
    </Link>
  )
}

function AttentionRow({ item, lead, onOpen }: { item: AttentionItem; lead: boolean; onOpen: Open }) {
  const navigate = useNavigate()
  switch (item.kind) {
    case 'monthReview': {
      const { review } = item
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--acc" aria-hidden="true"><ClockIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title home-attn__wrapnum">Review {formatMonthName(Number(review.month.slice(5, 7)))}</div>
          </div>
          <button type="button" className={act(lead)} onClick={() => navigate(`/insights/statements/${encodeURIComponent(review.month)}`)}>Review</button>
        </div>
      )
    }
    case 'match':
      return <MatchRow match={item.match} lead={lead} />
    case 'overdue': {
      const e = item.entry
      return (
        <ListRow onClick={() => onOpen(e, 'default')}
          leading={<span className="ui-ico ui-ico--neg"><AlertIcon /></span>}
          title={e.name}
          subtitle={<><Money amount={e.amount} currency={e.currency} nullText="No amount yet" /> · was due {formatShortDate(e.due_date)}</>}
          badges={<Badge tone="neg">Overdue</Badge>} />
      )
    }
    case 'missingAmount': {
      const e = item.entry
      return (
        <ListRow onClick={() => onOpen(e, 'amount')}
          leading={<span className="ui-ico ui-ico--warn"><AlertIcon /></span>}
          title={`${e.name} needs an amount`}
          subtitle={<>Due {formatShortDate(e.due_date)}{e.amount !== null && <> · usually <Money amount={e.amount} estimated currency={e.currency} /></>}</>}
          trailing={<span className="home-attn__cta">Set</span>} />
      )
    }
    case 'budget': {
      const b = item.row
      return (
        <LinkRow to="/plan?view=budgets"
          title={b.name}
          subtitle={b.budget === null ? undefined : <><Money amount={b.spent} whole /> of <Money amount={b.budget} whole /></>}
          badges={<Badge tone={b.pct !== null && b.pct >= 100 ? 'neg' : 'warn'}>{`${Math.round(b.pct ?? 0)}% used`}</Badge>} />
      )
    }
    case 'category': {
      const c = item.row
      return (
        <LinkRow to={`/insights/category/${encodeURIComponent(c.category_id ?? 'uncategorised')}`}
          leading={<span className="home-attn__emoji" aria-hidden="true">{c.icon}</span>}
          title={`${c.name} above usual`}
          subtitle={<><Money amount={c.this_month} whole /> this month{c.usual !== null && <> · usually <Money amount={c.usual} whole /></>}</>}
          badges={<Badge tone="warn">above usual</Badge>} />
      )
    }
    case 'billChange': {
      const { bill } = item
      const c = bill.change
      if (!c) return null
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--warn" aria-hidden="true"><AlertIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title home-attn__wrapnum">{changeTitle(bill.name, c)}</div>
          </div>
          <button type="button" className={act(lead)} onClick={() => navigate(`/insights/bills/${encodeURIComponent(bill.item_id)}`)}>See why</button>
          <button type="button" className="ui-iconbtn ui-iconbtn--bare home-attn__x" aria-label={`Dismiss ${bill.name}`}
            onClick={() => dismissBill(c.entry_id)}><XIcon /></button>
        </div>
      )
    }
    case 'cash':
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--warn" aria-hidden="true"><WalletIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title home-attn__wrapnum"><span className="ui-num">{formatMoney(item.amount)}</span> cash not logged yet</div>
          </div>
          <button type="button" className={act(lead)}
            onClick={() => navigate(`/new?mode=cash&take=none&amount=${item.amount.toFixed(2)}`)}>Log it</button>
        </div>
      )
    case 'pantry':
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--warn" aria-hidden="true"><PackageIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title home-attn__wrapnum">
              <span className="ui-num">{item.count}</span> {item.count === 1 ? 'pantry item' : 'pantry items'} running low
            </div>
          </div>
          <button type="button" className={act(lead)} onClick={() => navigate('/plan/pantry/list')}>List</button>
        </div>
      )
    case 'failed':
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--neg"><AlertIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title">1 change couldn't be saved</div>
            <div className="home-attn__sub">{item.change.error}</div>
          </div>
          <button type="button" className={act(lead)} onClick={() => void dismissFailed(item.change.id)}>Dismiss</button>
        </div>
      )
  }
}

function PackageIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" className="ui-icon">
      <path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" />
      <path d="M12 22V12" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="m7.5 4.27 9 5.15" />
    </svg>
  )
}

function MatchRow({ match, lead }: { match: MatchOut; lead: boolean }) {
  const actions = useMatchActions(match)
  return (
    <div className="home-attn__item">
      <span className="ui-ico ui-ico--acc"><LinkIcon /></span>
      <p className="home-attn__text">
        Payment <Money amount={match.transaction_amount} /> at {match.merchant ?? match.label} on{' '}
        {formatShortDate(match.transaction_date)} looks like <strong>{match.entry.name}</strong> due{' '}
        {formatShortDate(match.entry.due_date)}
      </p>
      <div className="home-attn__acts">
        <button type="button" className={act(lead)} disabled={actions.busy} onClick={() => void actions.link()}>Link</button>
        <button type="button" className="btn btn--sm btn--ghost" disabled={actions.busy} onClick={() => void actions.dismiss()}>Not this</button>
      </div>
    </div>
  )
}
