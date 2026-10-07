import { type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { formatShortDate } from '../../../ui/format'
import { ArrowInIcon, ArrowOutIcon, CoinsIcon, LandmarkIcon, LockIcon, PlusIcon, WalletIcon } from '../../../ui/icons'
import { Sheet } from '../../../ui/Sheet'
import { euros, initial, tint } from './format'
import { useCashWrite } from './hooks'
import { type CashMovementOut, num } from './types'

export interface MovementsProps {
  items: CashMovementOut[]
  meId: string
  /** Member names by id (former members fall back to a generic name). */
  names: Map<string, string>
  /** For the avatar tints: each member's place in the wallets list. */
  order: Map<string, number>
  currency: string
  canWrite: boolean
  monthLabel: string
}

interface Described { title: ReactNode; text: string; lead: ReactNode; amount: string | null }

/** Worded as the old /cash history (templates/cash/_list.html), plus the recount (spec §3.1, §4.2.3). */
function describe(m: CashMovementOut, p: Pick<MovementsProps, 'meId' | 'names' | 'order' | 'currency'>): Described {
  const e = (v: number, signed = false) => euros(v, p.currency, signed)
  const amount = num(m.amount)
  const tile = (icon: ReactNode, tone: string) => <span className={`ui-ico ui-ico--${tone}`} aria-hidden="true">{icon}</span>
  if (m.user_id !== p.meId) {
    const who = p.names.get(m.user_id) ?? 'Someone'
    const text = `${who} took ${e(amount)} from your stash`
    const lead = (
      <span className="cash-avatar" style={{ ['--tint' as string]: tint(p.order.get(m.user_id) ?? 5) }} aria-hidden="true">
        {initial(who)}
      </span>
    )
    return m.deleted
      ? { title: <><s>{text}</s> (deleted)</>, text: `${text} (deleted)`, lead, amount: e(amount) }
      : { title: text, text, lead, amount: e(amount) }
  }
  const plain = (text: string, lead: ReactNode, shown: string | null = e(amount)): Described => ({ title: text, text, lead, amount: shown })
  switch (m.kind) {
    case 'stash_in': return plain('Added to your stash', tile(<PlusIcon />, 'pos'))
    case 'put_back': return plain('Put back into your stash', tile(<ArrowInIcon />, 'acc'))
    case 'still_have': return plain(`Still have: ${e(amount)}`, tile(<WalletIcon />, 'neutral'), null)
    case 'stash_count': return plain(`Recounted your stash (${e(amount, true)})`, tile(<CoinsIcon />, 'warn'), null)
    case 'take':
      if (m.stash_owner_id === p.meId) return plain('Took from your stash', tile(<LockIcon />, 'acc'))
      if (m.stash_owner_id) return plain(`Took from ${p.names.get(m.stash_owner_id) ?? 'a former member'}'s stash`, tile(<LockIcon />, 'neutral'))
      return plain('Took from the bank', tile(<LandmarkIcon />, 'neutral'))
    default: return plain('Cash out', tile(<ArrowOutIcon />, 'neutral'))
  }
}

/** The month's movements, newest first. Your own rows open a sheet with Delete (spec §4.2.3). */
export function Movements(p: MovementsProps) {
  const [picked, setPicked] = useState<CashMovementOut | null>(null)
  if (p.items.length === 0) return <p className="cash-empty">No cash movements in {p.monthLabel}.</p>
  return (
    <>
      <ul className="ui-list cash-moves" aria-label="Movements">
        {p.items.map((m) => {
          const d = describe(m, p)
          const mine = m.user_id === p.meId
          const sub = [m.movement_date ? formatShortDate(m.movement_date) : null, m.note].filter(Boolean).join(' · ')
          const inner = (
            <>
              <span className="ui-row__lead">{d.lead}</span>
              <span className="ui-row__main">
                <span className="ui-row__title">{d.title}</span>
                {sub && <span className="ui-row__sub">{sub}</span>}
              </span>
              {d.amount && <span className="ui-row__end ui-num">{d.amount}</span>}
            </>
          )
          return (
            <li key={m.id} className="cash-move">
              {mine ? (
                <button type="button" className="ui-row" disabled={!p.canWrite} onClick={() => setPicked(m)}>{inner}</button>
              ) : (
                <div className="ui-row">{inner}</div>
              )}
              {m.transaction_id && (
                <Link className="cash-move__link" to={`/activity/${m.transaction_id}`}>Open the expense</Link>
              )}
            </li>
          )
        })}
      </ul>
      <DeleteSheet movement={picked} describe={(m) => describe(m, p).text} onClose={() => setPicked(null)} />
    </>
  )
}

function DeleteSheet({ movement, describe: text, onClose }: {
  movement: CashMovementOut | null; describe: (m: CashMovementOut) => string; onClose: () => void
}) {
  const { remove } = useCashWrite()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const close = () => { setError(null); onClose() }
  const confirm = async () => {
    if (!movement || busy) return
    setBusy(true)
    setError(null)
    const out = await remove(movement.id)
    setBusy(false)
    if (out.ok) close()
    else if (out.kind === 'rejected') setError(out.message)
  }
  return (
    <Sheet open={movement !== null} onClose={close} title="Cash entry"
      footer={
        <>
          <button type="button" className="btn btn--danger btn--block btn--lg" disabled={busy} onClick={() => void confirm()}>Delete</button>
          <button type="button" className="btn btn--block" onClick={close}>Cancel</button>
        </>
      }>
      {movement && (
        <div className="cash-del">
          <p className="cash-del__what">{text(movement)}{movement.movement_date ? ` · ${formatShortDate(movement.movement_date)}` : ''}</p>
          <p className="cash-del__ask">
            {movement.transaction_id ? 'Delete this take? The expense stays.' : 'Delete this cash entry?'}
          </p>
          {error && <p className="ui-field__error" role="alert">{error}</p>}
        </div>
      )}
    </Sheet>
  )
}
