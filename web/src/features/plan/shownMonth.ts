import { useSearchParams } from 'react-router'
import { monthsBetween, shiftMonth, todayISO } from '../../ui/format'

/** How far Plan's month steppers reach either side of this month. */
export const MAX_MONTH_SHIFT = 11
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/

/** The month the URL asks for (?month=YYYY-MM) within MAX_MONTH_SHIFT of today, else this month; `go` steps it. */
export function useShownMonth(): { month: string; go: (by: number) => void } {
  const [params, setParams] = useSearchParams()
  const current = todayISO().slice(0, 7)
  const asked = params.get('month')
  const month = asked && MONTH.test(asked) && Math.abs(monthsBetween(current, asked)) <= MAX_MONTH_SHIFT ? asked : current
  const go = (by: number) => {
    const next = new URLSearchParams(params)
    next.set('month', shiftMonth(month, by))
    setParams(next, { replace: true })
  }
  return { month, go }
}
