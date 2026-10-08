import { type Dispatch, useEffect } from 'react'
import { Segmented } from './bridge'
import { formatCents } from './currencies'
import { useStash } from './hooks/useComposerData'
import type { Action, ComposerState, TookFrom } from './state'

const OPTIONS = [
  { value: 'none', label: 'Not tracked' },
  { value: 'stash', label: 'My wallet' },
  { value: 'bank', label: 'Bank/ATM' },
] as const

export interface CashControlsProps {
  s: ComposerState
  dispatch: Dispatch<Action>
  householdCurrency: string
  onStash: (cents: number | null) => void
}

/** Method Cash: where the cash came from. "My wallet" shows (and checks against) the wallet balance. */
export function CashControls({ s, dispatch, householdCurrency, onStash }: CashControlsProps) {
  return (
    <div className="composer__cash">
      <Segmented<TookFrom> label="Took from" options={OPTIONS} value={s.tookFrom}
        onChange={(value) => dispatch({ type: 'setTookFrom', value })} />
      {s.tookFrom === 'stash' && <WalletLine householdCurrency={householdCurrency} onStash={onStash} />}
    </div>
  )
}

function WalletLine({ householdCurrency, onStash }: { householdCurrency: string; onStash: (cents: number | null) => void }) {
  const stash = useStash()
  useEffect(() => {
    onStash(stash)
    return () => onStash(null)
  }, [stash, onStash])
  if (stash === null) return null
  return <p className="composer__wallet">{`Wallet: ${formatCents(stash, householdCurrency)}`}</p>
}
