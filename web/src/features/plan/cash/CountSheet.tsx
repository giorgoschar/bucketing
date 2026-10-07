import { useRef, useState } from 'react'
import { Sheet } from '../../../ui/Sheet'
import { centsToString } from '../../composer/amount'
import { AmountField } from './AmountField'
import { euros, typedCents } from './format'
import { useCashWrite } from './hooks'

/**
 * Recount the stash (spec §4.4): what is physically there, 0 or more. The server stores the signed
 * correction (counted − balance) as a `stash_count` row; the preview shows the same sum first.
 */
export function CountSheet({ stash, currency, onClose }: { stash: number; currency: string; onClose: () => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLInputElement>(null)
  const { run } = useCashWrite()
  const cents = typedCents(text)
  const invalid = text.trim() !== '' && cents === null
  const book = Math.round(stash * 100)
  const e = (c: number, signed = false) => euros(c / 100, currency, signed)

  const save = async () => {
    if (cents === null || busy) return
    setBusy(true)
    setError(null)
    const out = await run({ kind: 'stash_count', amount: centsToString(cents) })
    setBusy(false)
    if (out.ok) onClose()
    else if (out.kind === 'rejected') setError(out.message)
  }

  return (
    <Sheet open onClose={onClose} title="Count your stash" initialFocus={ref}
      footer={
        <button type="button" className="btn btn--primary btn--block btn--lg" disabled={cents === null || busy}
          onClick={() => void save()}>Save count</button>
      }>
      <form className="cash-form" onSubmit={(ev) => { ev.preventDefault(); void save() }}>
        <AmountField label="Counted" value={text} onChange={(v) => { setText(v); setError(null) }} inputRef={ref}
          invalid={invalid} prompt="How much is in your stash right now?" />
        <p className="cash-preview" data-testid="count-preview">
          By the book <span className="ui-num">{e(book)}</span>
          {cents !== null && (
            <> → Counted <span className="ui-num">{e(cents)}</span> · correction <span className="ui-num">{e(cents - book, true)}</span></>
          )}
        </p>
        {error && <p className="ui-field__error" role="alert">{error}</p>}
      </form>
    </Sheet>
  )
}
