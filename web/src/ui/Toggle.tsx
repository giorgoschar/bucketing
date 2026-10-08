import './controls.css'

export interface ToggleProps {
  label: string
  checked: boolean
  onChange(next: boolean): void
  /** A request is in flight: taps are ignored and the switch says so. */
  busy?: boolean
  disabled?: boolean
}

export function Toggle({ label, checked, onChange, busy = false, disabled = false }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      className="toggle"
      aria-label={label}
      aria-checked={checked}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={() => {
        if (!busy && !disabled) onChange(!checked)
      }}
    >
      <span className="toggle__thumb" aria-hidden="true" />
    </button>
  )
}
