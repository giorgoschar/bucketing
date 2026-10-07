import { Sheet } from '../bridge'
import { addDays, dayLabel } from '../dates'
import './pickers.css'

export interface DateChipsProps { value: string; today: string; onPick: (iso: string) => void }

/** Today · Yesterday · the day before, and a native picker capped at today. */
export function DateChips({ value, today, onPick }: DateChipsProps) {
  const days = [today, addDays(today, -1), addDays(today, -2)]
  return (
    <div className="ck-chips ck-date">
      {days.map((d) => (
        <button key={d} type="button" className={d === value ? 'ck-chip on' : 'ck-chip'} aria-pressed={d === value}
          onClick={() => onPick(d)}>
          {dayLabel(d, today)}
        </button>
      ))}
      <input type="date" className="ck-date__input" aria-label="Pick a date" max={today} value={value}
        onChange={(e) => {
          const v = e.target.value
          if (v && v <= today) onPick(v)
        }} />
    </div>
  )
}

export function DateSheet({ open, onClose, value, today, onPick }: DateChipsProps & { open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} title="Date">
      <DateChips value={value} today={today} onPick={(d) => { onPick(d); onClose() }} />
    </Sheet>
  )
}
