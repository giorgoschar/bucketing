import './controls.css'

interface Option<T extends string> {
  value: T
  label: string
}
interface Common<T extends string> {
  label: string
  options: Option<T>[]
}
type Single<T extends string> = Common<T> & { multiple?: false; value: T; onChange(value: T): void }
type Multi<T extends string> = Common<T> & { multiple: true; value: T[]; onChange(value: T[]): void }

/** Single- or multi-select chips: buttons with aria-pressed in a labelled group. */
export function Chips<T extends string>(props: Single<T> | Multi<T>) {
  const pressed = (v: T) => (props.multiple ? props.value.includes(v) : props.value === v)
  const tap = (v: T) => {
    if (props.multiple) {
      props.onChange(pressed(v) ? props.value.filter((x) => x !== v) : [...props.value, v])
    } else if (props.value !== v) {
      props.onChange(v)
    }
  }
  return (
    <div className="chips" role="group" aria-label={props.label}>
      {props.options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="chip"
          aria-pressed={pressed(o.value)}
          onClick={() => tap(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
