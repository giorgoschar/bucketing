import type { EntryOut, UpcomingDayOut } from '../../data/types'
import { addDays, formatShortDate, parseISODate } from '../../ui/format'

/** The figure after a week's last entry in one month ("Net this month", spec §2.3). */
export interface WeekNet { month: string; net: number }

export interface UpcomingWeek {
  /** Monday of the week, ISO date. */
  start: string
  /** "This week", "Next week", "20–26 Oct", "28 Oct – 3 Nov". */
  label: string
  entries: EntryOut[]
  /** One per month the week's entries touch, in date order. */
  nets: WeekNet[]
}

/** Monday on or before `iso`. */
export function weekStart(iso: string): string {
  return addDays(iso, -((parseISODate(iso).getDay() + 6) % 7))
}

/** "20–26 Oct" within a month, "28 Oct – 3 Nov" across one (the turn of the year reads the same: "29 Dec – 4 Jan"). */
export function weekRange(start: string): string {
  const [d1, m1] = formatShortDate(start).split(' ')
  const [d2, m2] = formatShortDate(addDays(start, 6)).split(' ')
  return m1 === m2 ? `${d1}–${d2} ${m1}` : `${d1} ${m1} – ${d2} ${m2}`
}

const WEEKDAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short' })
/** "Tue 13". */
export const formatWeekdayDay = (iso: string): string => `${WEEKDAY.format(parseISODate(iso))} ${parseISODate(iso).getDate()}`

/** Days with entries, grouped Monday to Sunday. `today` decides "This week" and "Next week". */
export function groupUpcomingWeeks(days: UpcomingDayOut[], today: string): UpcomingWeek[] {
  const thisWeek = weekStart(today)
  const nextWeek = addDays(thisWeek, 7)
  const weeks = new Map<string, UpcomingWeek>()
  for (const d of [...days].filter((x) => x.entries.length > 0).sort((a, b) => a.date.localeCompare(b.date))) {
    const start = weekStart(d.date)
    let w = weeks.get(start)
    if (!w) {
      w = { start, label: start === thisWeek ? 'This week' : start === nextWeek ? 'Next week' : weekRange(start), entries: [], nets: [] }
      weeks.set(start, w)
    }
    w.entries.push(...d.entries)
    // The last day of a month wins: its net follows the week's last entry in that month.
    const month = d.date.slice(0, 7)
    const last = w.nets[w.nets.length - 1]
    if (last?.month === month) last.net = d.net_this_month
    else w.nets.push({ month, net: d.net_this_month })
  }
  return [...weeks.values()]
}
