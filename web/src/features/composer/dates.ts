const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const parse = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** The device's local calendar day. Never toISOString(): that is the UTC day. */
export const todayLocal = (now: Date = new Date()): string => iso(now)

export function addDays(day: string, n: number): string {
  const d = parse(day)
  d.setDate(d.getDate() + n)
  return iso(d)
}

export const shortDate = (day: string): string => {
  const d = parse(day)
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

export function dayLabel(day: string, today: string): string {
  if (day === today) return 'Today'
  if (day === addDays(today, -1)) return 'Yesterday'
  return `${DAYS[parse(day).getDay()]} ${shortDate(day)}`
}

export function rangeLabel(start: string | null, end: string | null): string {
  if (!start || !end) return start ? shortDate(start) : ''
  const a = parse(start)
  const b = parse(end)
  return a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()
    ? `${a.getDate()}–${b.getDate()} ${MONTHS[b.getMonth()]}`
    : `${shortDate(start)} – ${shortDate(end)}`
}
