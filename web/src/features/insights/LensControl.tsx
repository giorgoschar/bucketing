import type { KeyboardEvent } from 'react'

/** The lens: a labelled radio group (roving tab stop, arrow keys move the choice) in 2a's segmented look. */
export function LensControl({ label, options, value, onChange }: {
  label: string; options: { value: string; label: string }[]; value: string; onChange(v: string): void
}) {
  const move = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const at = (i + step + options.length) % options.length
    onChange(options[at].value)
    ;(e.currentTarget.parentElement?.children[at] as HTMLElement | undefined)?.focus()
  }
  return (
    <div className="ui-seg insights__lens" role="radiogroup" aria-label={label}>
      {options.map((o, i) => (
        <button key={o.value} type="button" role="radio" className="ui-seg__opt" aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1} onClick={() => onChange(o.value)} onKeyDown={(e) => move(e, i)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
