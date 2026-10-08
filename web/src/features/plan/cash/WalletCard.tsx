import { Badge } from '../../../ui/Badge'
import { CheckIcon } from '../../../ui/icons'
import { CENT_EPS, euros, initial, tint, walletSum } from './format'
import type { CashWalletMemberOut } from './types'

export interface WalletCardProps {
  member: CashWalletMemberOut
  index: number
  currency: string
  canWrite: boolean
  /** Log it and Still have write into today's month, so they show only on this month's cards (review I5). */
  current: boolean
  onLogIt: (amount: number) => void
  onStillHave: () => void
}

/** One member's month: household-visible. The viewer's own card also has Log it and Still have. */
export function WalletCard({ member, index, currency, canWrite, current, onLogIt, onStillHave }: WalletCardProps) {
  const { took, inHand, logged, crossMonth, overLogged, notLogged } = walletSum(member)
  const open = notLogged > CENT_EPS
  const e = (v: number) => euros(v, currency)
  // The terms the cells leave out, only when they count (polish C6): with them the shown sum is the server's.
  const terms = [
    ...(crossMonth > CENT_EPS ? [{ op: '−', k: 'Logged from last month', v: crossMonth }] : []),
    ...(overLogged > CENT_EPS ? [{ op: '+', k: 'Logged more than taken', v: overLogged }] : []),
  ]
  const sentence =
    `Took ${e(took)}${inHand !== null ? ` − In hand ${e(inHand)}` : ''} − Logged ${e(logged)}` +
    terms.map((t) => ` ${t.op} ${t.k} ${e(t.v)}`).join('') +
    (open ? ` = ${e(notLogged)} not yet logged` : '')
  const own = member.is_me
  const acts = own && current
  return (
    <article className="ui-card cash-wallet" aria-label={`${member.name}'s wallet`}>
      <div className="cash-wallet__head">
        <span className="cash-avatar" style={{ ['--tint' as string]: tint(index) }} aria-hidden="true">{initial(member.name)}</span>
        <span className="cash-wallet__name">{member.name}{own && <span className="cash-wallet__you"> (you)</span>}</span>
        {open && acts ? (
          <button type="button" className="btn btn--sm btn--primary" disabled={!canWrite} onClick={() => onLogIt(notLogged)}>Log it</button>
        ) : !open ? (
          <Badge tone="pos" icon={<CheckIcon />}>All logged</Badge>
        ) : null}
      </div>
      <p className="ui-sr">{sentence}</p>
      <div className={inHand !== null ? 'cash-eq cash-eq--four' : 'cash-eq'} aria-hidden="true">
        <Cell k="Took" v={e(took)} />
        {inHand !== null && <><Op>−</Op><Cell k="In hand" v={e(inHand)} /></>}
        <Op>−</Op>
        <Cell k="Logged" v={e(logged)} />
        <Op>=</Op>
        <Cell k={open ? 'Not yet logged' : 'Left to log'} v={e(open ? notLogged : 0)} tone={open ? 'res' : 'ok'} />
      </div>
      {terms.length > 0 && (
        <ul className="cash-terms" aria-hidden="true">
          {terms.map((t) => (
            <li key={t.k} className="cash-terms__row">
              <span className="cash-terms__k">{t.op} {t.k}</span>
              <span className="cash-terms__v ui-num">{e(t.v)}</span>
            </li>
          ))}
        </ul>
      )}
      {acts && (
        <div className="cash-wallet__foot">
          <button type="button" className="btn btn--sm" disabled={!canWrite} onClick={onStillHave}>Still have</button>
          {!canWrite && <span className="cash-offline-hint">Connect to change cash</span>}
        </div>
      )}
    </article>
  )
}

function Cell({ k, v, tone }: { k: string; v: string; tone?: 'res' | 'ok' }) {
  return (
    <span className={tone ? `cash-eq__cell cash-eq__cell--${tone}` : 'cash-eq__cell'}>
      <span className="cash-eq__k">{k}</span>
      <span className="cash-eq__v ui-num">{v}</span>
    </span>
  )
}
const Op = ({ children }: { children: string }) => <span className="cash-eq__op">{children}</span>
