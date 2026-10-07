import './ui-2c.css'

/** The selection tick. Decorative: the row carries aria-selected. */
export function Check({ checked }: { checked: boolean }) {
  return (
    <span className={checked ? 'check on' : 'check'} aria-hidden="true">
      {checked && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 12l5 5 9-10" /></svg>
      )}
    </span>
  )
}
