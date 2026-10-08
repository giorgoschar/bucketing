import { type RefObject, useId } from 'react'

export interface AmountFieldProps {
  label: string
  value: string
  onChange: (v: string) => void
  inputRef: RefObject<HTMLInputElement | null>
  /** Shown when what was typed is not an amount. */
  invalid: boolean
  prompt?: string
}

/** The big amount input of the cash sheets: decimal keyboard, "12,50" or "12.50" (composer parsing). */
export function AmountField({ label, value, onChange, inputRef, invalid, prompt }: AmountFieldProps) {
  const id = useId()
  const err = useId()
  return (
    <div className="cash-amount">
      {prompt && <p className="cash-amount__prompt">{prompt}</p>}
      <label className="ui-sr" htmlFor={id}>{label}</label>
      <div className="cash-amount__box">
        <span className="cash-amount__sym" aria-hidden="true">€</span>
        <input id={id} ref={inputRef} className="cash-amount__input ui-num" inputMode="decimal" autoComplete="off"
          enterKeyHint="done" placeholder="0" value={value} aria-invalid={invalid || undefined}
          aria-describedby={invalid ? err : undefined} onChange={(e) => onChange(e.target.value)} />
      </div>
      {invalid && <p id={err} className="ui-field__error cash-amount__err">Enter an amount like 40 or 12,50</p>}
    </div>
  )
}
