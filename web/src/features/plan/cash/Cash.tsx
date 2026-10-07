import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { CachedQuery } from '../../../data/cachedQuery'
import { useOnline } from '../../../data/online'
import { useHousehold } from '../../../data/reads'
import { formatMonthLabel } from '../../../ui/format'
import { CloudOffIcon, EyeIcon } from '../../../ui/icons'
import { QueryView } from '../../../ui/QueryView'
import { MonthStepper } from '../MonthStepper'
import { useShownMonth } from '../shownMonth'
import { CashSheet } from './CashSheet'
import { CountSheet } from './CountSheet'
import { useCashMovements, useCashWallets } from './hooks'
import { Movements } from './Movements'
import { StashCard } from './StashCard'
import { type CashWalletsOut, num } from './types'
import { WalletCard } from './WalletCard'
import './cash.css'

export type CashSheetMode = 'take' | 'put_back' | 'still_have' | 'add'
type Open = { kind: 'cash'; mode: CashSheetMode } | { kind: 'count' } | null

/** Plan › Cash (spec §4.2): my stash, the month's wallets, the month's movements. */
export function Cash() {
  const { month, go } = useShownMonth()
  const wallets = useCashWallets(month)
  const online = useOnline()
  // Stepping to a month not loaded yet keeps the screen (and the stepper under the finger): the stash is
  // all-time, so the last one shown stays true while the new month's wallets load.
  const [last, setLast] = useState<CashWalletsOut | undefined>(undefined)
  if (wallets.data && wallets.data !== last) setLast(wallets.data)
  const shown = wallets.data ?? (wallets.isLoading ? last : undefined)
  return (
    <div className="cash">
      {shown ? (
        <>
          {wallets.stale && (
            <p className="ui-banner" role="status"><CloudOffIcon />Offline · showing saved cash</p>
          )}
          <CashBody stash={num(shown.stash)} wallets={wallets} month={month} go={go} canWrite={online} />
        </>
      ) : (
        <QueryView result={wallets} showBanner={false} noDataText="No saved cash yet. Connect once to load Cash.">
          {() => null}
        </QueryView>
      )}
    </div>
  )
}

interface BodyProps {
  stash: number
  wallets: CachedQuery<CashWalletsOut>
  month: string
  go: (by: number) => void
  canWrite: boolean
}

function CashBody({ stash, wallets, month, go, canWrite }: BodyProps) {
  const navigate = useNavigate()
  const currency = useHousehold().data?.default_currency ?? 'EUR'
  const movements = useCashMovements(month)
  const [open, setOpen] = useState<Open>(null)
  const members = wallets.data?.members ?? []
  const me = members.find((m) => m.is_me)
  const names = new Map(members.map((m) => [m.member_id, m.name]))
  const order = new Map(members.map((m, i) => [m.member_id, i]))
  const label = formatMonthLabel(month)
  return (
    <>
      <StashCard stash={stash} currency={currency} canWrite={canWrite}
        onAdd={() => setOpen({ kind: 'cash', mode: 'add' })}
        onTake={() => setOpen({ kind: 'cash', mode: 'take' })}
        onCount={() => setOpen({ kind: 'count' })} />

      <section className="cash-sec" aria-labelledby="cash-wallets-title">
        <div className="ui-sec cash-sec__head">
          <h2 id="cash-wallets-title" className="ui-sec__title">Wallets</h2>
          <span className="cash-shared"><EyeIcon />Household sees these</span>
        </div>
        <MonthStepper month={month} onStep={go} />
        <QueryView result={wallets} showBanner={false} noDataText="No saved wallets for this month yet.">
          {(w) => (
            <div className="cash-wallets">
              {w.members.map((m, i) => (
                <WalletCard key={m.member_id} member={m} index={i} currency={currency} canWrite={canWrite}
                  onLogIt={(amount) => navigate(`/new?mode=cash&take=none&amount=${amount.toFixed(2)}`)}
                  onStillHave={() => setOpen({ kind: 'cash', mode: 'still_have' })} />
              ))}
            </div>
          )}
        </QueryView>
      </section>

      {open?.kind === 'cash' && (
        <CashSheet mode={open.mode} stash={stash} members={members} currency={currency} onClose={() => setOpen(null)} />
      )}
      {open?.kind === 'count' && <CountSheet stash={stash} currency={currency} onClose={() => setOpen(null)} />}

      {me && (
        <section className="cash-sec" aria-labelledby="cash-moves-title">
          <div className="ui-sec"><h2 id="cash-moves-title" className="ui-sec__title">Movements</h2></div>
          <QueryView result={movements} showBanner={false} noDataText="No saved movements for this month yet.">
            {(mv) => (
              <Movements items={mv.items} meId={me.member_id} names={names} order={order}
                currency={currency} canWrite={canWrite} monthLabel={label} />
            )}
          </QueryView>
        </section>
      )}
    </>
  )
}
