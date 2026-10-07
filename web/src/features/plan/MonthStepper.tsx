import { formatMonthLabel, monthsBetween, todayISO } from '../../ui/format'
import { ChevronLeftIcon, ChevronRightIcon } from '../../ui/icons'
import { MAX_MONTH_SHIFT } from './shownMonth'

/** "‹ Oct 2026 ›": Plan › Month and Plan › Cash share it (cash spec §4.2). */
export function MonthStepper({ month, onStep }: { month: string; onStep: (by: number) => void }) {
  const offset = monthsBetween(todayISO().slice(0, 7), month)
  return (
    <div className="plan-switch">
      <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Previous month"
        disabled={offset <= -MAX_MONTH_SHIFT} onClick={() => onStep(-1)}><ChevronLeftIcon /></button>
      <h3 className="plan-switch__label" aria-live="polite">{formatMonthLabel(month)}</h3>
      <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Next month"
        disabled={offset >= MAX_MONTH_SHIFT} onClick={() => onStep(1)}><ChevronRightIcon /></button>
    </div>
  )
}
