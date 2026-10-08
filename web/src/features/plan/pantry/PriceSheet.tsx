import { useId, useRef, useState } from 'react'
import { useOnline } from '../../../data/online'
import { formatMoney, todayISO } from '../../../ui/format'
import { Sheet } from '../../../ui/Sheet'
import { OFFLINE_WRITE } from './BarcodeSheet'
import { useRetailers, useStockWrites } from './hooks'
import { typedPrice } from './types'

const FUTURE_DATE = 'Pick today or an earlier day'

/** Detail › Log a price (polish P1, C3): what you paid, where and when. Online only. */
export function PriceSheet({ id, name, onClose }: { id: string; name: string; onClose: () => void }) {
  const online = useOnline()
  const writes = useStockWrites(id)
  const retailers = useRetailers(true)
  const base = useId()
  const today = todayISO()
  const [text, setText] = useState('')
  const [store, setStore] = useState('')
  const [date, setDate] = useState(today)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const priceRef = useRef<HTMLInputElement>(null)

  const price = typedPrice(text)
  const badPrice = text.trim() !== '' && price === null
  const future = date > today
  const ready = online && !busy && price !== null && store !== '' && date !== '' && !future

  const save = async () => {
    if (!ready || price === null) return
    setBusy(true)
    setError(null)
    const out = await writes.logPrice({ price, retailer: store, date })
    setBusy(false)
    if (out.ok) return onClose()
    if (out.kind !== 'auth') setError(out.message)
  }

  return (
    <Sheet open onClose={onClose} title="Log a price" initialFocus={priceRef}
      footer={
        <div className="pantry-sheet__foot">
          {!online && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
          <button type="submit" form={`${base}-form`} className="btn btn--primary btn--block btn--lg" disabled={!ready}>
            {price === null ? 'Log price' : `Log ${formatMoney(price)}`}
          </button>
        </div>
      }>
      <form id={`${base}-form`} className="pantry-manual" noValidate onSubmit={(e) => { e.preventDefault(); void save() }}>
        <p className="pantry-lookup__note">What you paid for {name}</p>
        <div className="ui-field">
          <label className="ui-field__label" htmlFor={`${base}-price`}>Price</label>
          <div className="pantry-price-in">
            <span className="pantry-price-in__sym" aria-hidden="true">€</span>
            <input ref={priceRef} id={`${base}-price`} className="ui-input ui-num" inputMode="decimal" autoComplete="off"
              enterKeyHint="done" placeholder="0,00" value={text} aria-invalid={badPrice || undefined}
              aria-describedby={badPrice ? `${base}-price-err` : undefined}
              onChange={(e) => { setText(e.target.value); setError(null) }} />
          </div>
          {badPrice && <p id={`${base}-price-err`} className="ui-field__error">Enter a price like 1,29</p>}
        </div>
        <div className="ui-field">
          <label className="ui-field__label" htmlFor={`${base}-store`}>Store</label>
          <select id={`${base}-store`} className="ui-input" value={store} disabled={!retailers}
            onChange={(e) => { setStore(e.target.value); setError(null) }}>
            <option value="" disabled>{retailers ? 'Choose a store' : 'Loading stores…'}</option>
            {retailers?.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
          </select>
        </div>
        <div className="ui-field">
          <label className="ui-field__label" htmlFor={`${base}-date`}>Date</label>
          <input id={`${base}-date`} className="ui-input" type="date" value={date} max={today}
            aria-invalid={future || undefined} aria-describedby={future ? `${base}-date-err` : undefined}
            onChange={(e) => { setDate(e.target.value); setError(null) }} />
          {future && <p id={`${base}-date-err`} className="ui-field__error">{FUTURE_DATE}</p>}
        </div>
        {error && <p className="ui-field__error" role="alert">{error}</p>}
      </form>
    </Sheet>
  )
}
