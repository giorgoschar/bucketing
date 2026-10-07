import { Badge } from '../../../ui/Badge'
import { CheckIcon } from '../../../ui/icons'
import { CENT_EPS, euros, initial, tint, walletSum } from './format'
import type { CashWalletMemberOut } from './types'

export interface WalletCardProps {
  member: CashWalletMemberOut
  index: number
  currency: string
  canWrite: boolean
  onLogIt: (amount: number) => void
  onStillHave: () => void
}

/** One member's month: household-visible. The viewer's own card also has Log it and Still have. */
export function WalletCard({ member, index, currency, canWrite, onLogIt, onStillHave }: WalletCardProps) {
  const { took, inHand, logged, notLogged } = walletSum(member)
  const open = notLogged > CENT_EPS
  const e = (v: number) => euros(v, currency)
  const sentence =
    `Took ${e(took)}${inHand !== null ? ` − In hand ${e(inHand)}` : ''} − Logged ${e(logged)}` +
    (open ? ` = ${e(notLogged)} not yet logged` : '')
  const own = member.is_me
  return (
    <article className="ui-card cash-wallet" aria-label={`${member.name}'s wallet`}>
      <div className="cash-wallet__head">
        <span className="cash-avatar" style={{ ['--tint' as string]: tint(index) }} aria-hidden="true">{initial(member.name)}</span>
        <span className="cash-wallet__name">{member.name}{own && <span className="cash-wallet__you"> (you)</span>}</span>
        {open && own ? (
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
      {own && (
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
