import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { EntryOut, MatchOut } from '../../data/types'
import { dismissFailed } from '../../offline/useQueue'
import { Badge } from '../../ui/Badge'
import { formatMoney, formatShortDate } from '../../ui/format'
import { AlertIcon, CheckIcon, LinkIcon, WalletIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { EntrySheet, type EntryIntent } from '../plan/EntrySheet'
import type { AttentionItem } from './attention'
import { useAttention, useMatchActions } from './hooks'
import './home.css'

export function NeedsAttention() {
  const { items, ready } = useAttention()
  const [open, setOpen] = useState<{ entry: EntryOut; intent: EntryIntent } | null>(null)
  if (!ready && items.length === 0) return null
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
        <div className="ui-list">
          {items.map((it) => (
            <div key={it.key} className="home-attn__wrap" data-attn={it.kind}>
              <AttentionRow item={it} onOpen={(entry, intent) => setOpen({ entry, intent })} />
            </div>
          ))}
        </div>
      )}
      <EntrySheet entry={open?.entry ?? null} intent={open?.intent} onClose={() => setOpen(null)} />
    </section>
  )
}

function AttentionRow({ item, onOpen }: { item: AttentionItem; onOpen: (e: EntryOut, intent: EntryIntent) => void }) {
  const navigate = useNavigate()
  switch (item.kind) {
    case 'match':
      return <MatchRow match={item.match} />
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
        <ListRow onClick={() => navigate('/plan?view=budgets')}
          title={b.name}
          subtitle={b.budget === null ? undefined : <><Money amount={b.spent} whole /> of <Money amount={b.budget} whole /></>}
          badges={<Badge tone={b.pct !== null && b.pct >= 100 ? 'neg' : 'warn'}>{`${Math.round(b.pct ?? 0)}% used`}</Badge>} />
      )
    }
    case 'category': {
      const c = item.row
      return (
        <ListRow onClick={() => navigate('/plan?view=month')}
          leading={<span className="home-attn__emoji" aria-hidden="true">{c.icon}</span>}
          title={`${c.name} above usual`}
          subtitle={<><Money amount={c.this_month} whole /> this month{c.usual !== null && <> · usually <Money amount={c.usual} whole /></>}</>}
          badges={<Badge tone="warn">above usual</Badge>} />
      )
    }
    case 'cash':
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--warn" aria-hidden="true"><WalletIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title home-attn__wrapnum"><span className="ui-num">{formatMoney(item.amount)}</span> cash not logged yet</div>
          </div>
          <button type="button" className="btn btn--sm btn--primary"
            onClick={() => navigate(`/new?mode=cash&take=none&amount=${item.amount.toFixed(2)}`)}>Log it</button>
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
          <button type="button" className="btn btn--sm" onClick={() => void dismissFailed(item.change.id)}>Dismiss</button>
        </div>
      )
  }
}

function MatchRow({ match }: { match: MatchOut }) {
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
        <button type="button" className="btn btn--sm btn--primary" disabled={actions.busy} onClick={() => void actions.link()}>Link</button>
        <button type="button" className="btn btn--sm" disabled={actions.busy} onClick={() => void actions.dismiss()}>Not this</button>
      </div>
    </div>
  )
}
