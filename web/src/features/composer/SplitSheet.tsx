import { useState } from 'react'
import { type Member, Segmented, Sheet } from './bridge'
import { formatCents } from './currencies'
import { memberName } from './pickers/labels'
import {
  amountShares, equalShares, invalidInputs, ownShares, percentShares, splitProblem, toShareList, typedFromShares,
} from './splits'
import type { Share, SplitMode } from './state'
import './split.css'

export interface SplitSheetProps {
  open: boolean
  onClose: () => void
  /** 'split': the payer takes the remainder. 'own': "Who paid what", every amount typed. */
  variant: 'split' | 'own'
  totalCents: number
  currency: string
  members: Member[]
  /** The payer (split variant); null for own share. */
  payerId: string | null
  initial: { mode: SplitMode; shares: Share[] }
  onDone: (r: { mode: SplitMode; shares: Share[] }) => void
}

const MODES = [
  { value: 'equal', label: 'Equal' },
  { value: 'amounts', label: 'Amounts' },
  { value: 'percent', label: 'Percent' },
] as const

/** Opens fresh each time, from the composer's current shares (spec §4.6). */
export function SplitSheet(props: SplitSheetProps) {
  if (!props.open) return null
  return <SplitBody {...props} />
}

function SplitBody({ onClose, variant, totalCents, currency, members, payerId, initial, onDone }: SplitSheetProps) {
  const ids = members.map((m) => m.user_id)
  const own = variant === 'own'
  const [mode, setMode] = useState<SplitMode>(own ? 'amounts' : initial.mode)
  const [typed, setTyped] = useState<Record<string, string>>(() =>
    own || initial.mode === 'amounts' ? typedFromShares(initial.shares) : {})
  const payer = payerId ?? ids[0]
  const shares =
    own ? ownShares(ids, typed)
    : mode === 'equal' ? equalShares(totalCents, ids, payer)
    : mode === 'amounts' ? amountShares(totalCents, ids, payer, typed)
    : percentShares(totalCents, ids, payer, typed)
  const unitOf = own || mode === 'amounts' ? 'amount' : 'percent'
  const bad = mode === 'equal' && !own ? [] : invalidInputs(typed, unitOf)
  const problem = bad.length ? 'invalid' : splitProblem(totalCents, shares, own)
  const assigned = Object.values(shares).reduce((a, x) => a + x, 0)
  const money = (c: number) => formatCents(c, currency)
  const pct = (c: number) => (totalCents > 0 ? Math.round((Math.max(c, 0) / totalCents) * 100) : 0)
  const switchMode = (m: SplitMode) => {
    setMode(m)
    setTyped({}) // amounts and percents mean different things
  }
  const done = () => {
    onDone({ mode, shares: toShareList(ids, shares) })
    onClose()
  }

  return (
    <Sheet open onClose={onClose} title={own ? 'Who paid what' : 'Split'}
      footer={<button type="button" className="btn btn--primary btn--lg btn--block" disabled={problem !== null} onClick={done}>Done</button>}>
      <p className="ck-split__total">Total <span className="ck-split__num">{money(totalCents)}</span></p>
      {!own && <Segmented<SplitMode> label="Split by" options={MODES} value={mode} onChange={switchMode} />}

      <div className="ck-split__card">
        <div className="ck-split__bar" role="img"
          aria-label={members.map((m) => `${memberName(m)} ${money(shares[m.user_id] ?? 0)}`).join(', ')}>
          {members.map((m, i) => (
            <span key={m.user_id} className="ck-split__seg"
              style={{ flexGrow: Math.max(shares[m.user_id] ?? 0, 0), background: `var(--c${(i % 6) + 1})` }} />
          ))}
        </div>
        {members.map((m, i) => {
          const name = memberName(m)
          const share = shares[m.user_id] ?? 0
          const editable = own || (mode !== 'equal' && m.user_id !== payer)
          const unit = mode === 'percent' && !own ? 'percent' : 'amount'
          return (
            <div key={m.user_id} className="ck-split__row">
              <span className="ck-split__avatar" style={{ ['--tint' as string]: `var(--c${(i % 6) + 1})` }} aria-hidden="true">
                {name.slice(0, 1).toUpperCase()}
              </span>
              <span className="ck-split__who">
                <span className="ck-split__name">{name}</span>
                <span className="ck-split__sub">
                  {!own && m.user_id === payer && mode !== 'equal' ? `${pct(share)}% · gets the rest` : `${pct(share)}%`}
                </span>
              </span>
              {editable ? (
                <span className="ck-split__field">
                  <input className="ck-split__input" aria-label={`${name} ${unit}`} inputMode="decimal" autoComplete="off"
                    aria-invalid={bad.includes(m.user_id) || undefined}
                    value={typed[m.user_id] ?? ''} placeholder={unit === 'percent' ? '0' : '0.00'}
                    onChange={(e) => setTyped((t) => ({ ...t, [m.user_id]: e.target.value }))} />
                  {unit === 'percent' && <span className="ck-split__unit" aria-hidden="true">%</span>}
                </span>
              ) : (
                <span className={share < 0 ? 'ck-split__amount ck-split__amount--bad' : 'ck-split__amount'}>{money(share)}</span>
              )}
            </div>
          )
        })}
      </div>

      <p className={problem ? 'ck-split__note ck-split__note--bad' : 'ck-split__note'}>
        {problem === 'invalid'
          ? unitOf === 'percent' ? 'Use a number like 12.5' : 'Use a number like 12.50'
          : own
          ? `Left to assign ${money(totalCents - assigned)}`
          : `${memberName(members.find((m) => m.user_id === payer))} covers the remaining ${money(shares[payer] ?? 0)}`}
      </p>
    </Sheet>
  )
}
