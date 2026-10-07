import './ui-2c.css'

type Props = { label: string; pressed?: boolean; count?: number; disabled?: boolean; onClick?: () => void }

export function Chip({ label, pressed = false, count, disabled, onClick }: Props) {
  return (
    <button type="button" className={pressed ? 'chip on' : 'chip'} aria-pressed={pressed} disabled={disabled} onClick={onClick}>
      <span>{label}</span>
      {count !== undefined && <>{' '}<span className="count">{count}</span></>}
    </button>
  )
}
