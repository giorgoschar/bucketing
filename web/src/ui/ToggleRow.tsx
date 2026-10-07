import { useId } from 'react'
import './composer-kit.css'

export interface ToggleRowProps {
  label: string
  hint?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}

export function ToggleRow({ label, hint, checked, onChange, disabled }: ToggleRowProps) {
  const hintId = useId()
  return (
    <div className="ck-toggle-row">
      <span className="ck-toggle-row__text">
        <span className="ck-toggle-row__label">{label}</span>
        {hint && <span id={hintId} className="ck-toggle-row__hint">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        aria-describedby={hint ? hintId : undefined}
        disabled={disabled}
        className={checked ? 'toggle on' : 'toggle'}
        onClick={() => onChange(!checked)}
      />
    </div>
  )
}
