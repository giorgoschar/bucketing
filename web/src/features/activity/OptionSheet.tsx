import { Check } from '../../ui/Check'
import { Sheet } from '../../ui/Sheet'

export type Option = { value: string; label: string; hint?: string }
type Props = {
  open: boolean
  title: string
  options: Option[]
  value: string
  note?: string
  onPick: (value: string) => void
  onClose: () => void
}

export function OptionSheet({ open, title, options, value, note, onPick, onClose }: Props) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      {note && <p className="option-note">{note}</p>}
      <ul className="ui-list feed__list" role="listbox" aria-label={title}>
        {options.map((o) => (
          <li key={o.value} role="option" aria-selected={o.value === value}>
            <button
              type="button"
              className="ui-row option"
              onClick={() => {
                onPick(o.value)
                onClose()
              }}
            >
              <span className="ui-row__main">
                <span className="ui-row__title">{o.label}</span>
                {o.hint && <span className="ui-row__sub">{o.hint}</span>}
              </span>
              <Check checked={o.value === value} />
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  )
}
