import { AlertIcon, CoinsIcon, LockIcon, PlusIcon, WalletIcon } from '../../../ui/icons'
import { Money } from '../../../ui/Money'
import { CENT_EPS, euros } from './format'

export interface StashCardProps {
  stash: number
  currency: string
  /** Offline: every write is disabled (spec §4.7). */
  canWrite: boolean
  onAdd: () => void
  onTake: () => void
  onCount: () => void
}

/** My stash (spec §4.2.1): private, with Add, Take and Count; a negative book balance asks for a count. */
export function StashCard({ stash, currency, canWrite, onAdd, onTake, onCount }: StashCardProps) {
  const short = stash < -CENT_EPS
  return (
    <section className="ui-card cash-stash" aria-labelledby="cash-stash-title">
      <div className="cash-stash__top">
        <span className="ui-ico ui-ico--acc" aria-hidden="true"><LockIcon /></span>
        <div className="cash-stash__fig">
          <h2 id="cash-stash-title" className="cash-stash__label">My stash</h2>
          <Money className={short ? 'ui-figure cash-stash__amount ui-neg' : 'ui-figure cash-stash__amount'}
            amount={stash} currency={currency} />
          {short && <p className="cash-stash__book">Balance by the book</p>}
        </div>
        <span className="cash-private"><LockIcon />Only you see this</span>
      </div>
      {short && (
        <div className="cash-short" role="note">
          <span className="ui-ico ui-ico--warn cash-short__ico" aria-hidden="true"><AlertIcon /></span>
          <div className="cash-short__text">
            <p className="cash-short__title">Your stash may be {euros(-stash, currency)} short</p>
            <p className="cash-short__body">Someone took more than the balance. Count it and correct.</p>
          </div>
          <button type="button" className="btn btn--primary btn--block cash-short__btn" disabled={!canWrite} onClick={onCount}>
            <CoinsIcon />Count now
          </button>
        </div>
      )}
      <div className="cash-stash__acts">
        <button type="button" className="btn" disabled={!canWrite} onClick={onAdd}><PlusIcon />Add</button>
        <button type="button" className="btn btn--primary" disabled={!canWrite} onClick={onTake}><WalletIcon />Take</button>
        <button type="button" className="btn" disabled={!canWrite} onClick={onCount}><CoinsIcon />Count</button>
      </div>
      {!canWrite && <p className="cash-offline-hint">Connect to change cash</p>}
    </section>
  )
}
