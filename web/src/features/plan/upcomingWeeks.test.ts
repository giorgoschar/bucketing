import { expect, it } from 'vitest'
import { day, entry } from '../../test/fixtures'
import { formatWeekdayDay, groupUpcomingWeeks, weekRange, weekStart } from './upcomingWeeks'

const e = (id: string, due: string) => entry({ id, due_date: due })

it('groups Monday to Sunday and labels this week, next week, then the range', () => {
  // Wed 7 Oct 2026: this week 5-11 Oct, next 12-18, then 19-25 and 26 Oct - 1 Nov.
  const weeks = groupUpcomingWeeks([
    day('2026-10-05', [e('a', '2026-10-05')], 100),
    day('2026-10-11', [e('b', '2026-10-11')], 90),
    day('2026-10-12', [e('c', '2026-10-12')], 80),
    day('2026-10-20', [e('d', '2026-10-20')], 70),
  ], '2026-10-07')
  expect(weeks.map((w) => [w.label, w.entries.map((x) => x.id)])).toEqual([
    ['This week', ['a', 'b']], ['Next week', ['c']], ['19–25 Oct', ['d']],
  ])
})

it('Sunday belongs to the week that began on the Monday before', () => {
  expect(weekStart('2026-10-11')).toBe('2026-10-05')
  expect(weekStart('2026-10-12')).toBe('2026-10-12')
  expect(weekStart('2026-10-05')).toBe('2026-10-05')
})

it('skips days without entries and sorts by date', () => {
  const weeks = groupUpcomingWeeks([day('2026-10-20', [e('d', '2026-10-20')], 7), day('2026-10-14', [], 9), day('2026-10-13', [e('c', '2026-10-13')], 8)], '2026-10-07')
  expect(weeks.map((w) => w.entries.map((x) => x.id))).toEqual([['c'], ['d']])
})

it('the per-week net is the last entry day\'s net_this_month', () => {
  const [w] = groupUpcomingWeeks([day('2026-10-13', [e('a', '2026-10-13')], 500), day('2026-10-15', [e('b', '2026-10-15')], 420)], '2026-10-07')
  expect(w.nets).toEqual([{ month: '2026-10', net: 420 }])
})

it('a week crossing a month shows the net once per month it touches', () => {
  const [w] = groupUpcomingWeeks([
    day('2026-10-27', [e('a', '2026-10-27')], 300), day('2026-10-30', [e('b', '2026-10-30')], 250), day('2026-11-01', [e('c', '2026-11-01')], 40),
  ], '2026-10-07')
  expect(w.label).toBe('26 Oct – 1 Nov')
  expect(w.nets).toEqual([{ month: '2026-10', net: 250 }, { month: '2026-11', net: 40 }])
})

it('the turn of the year: a week crossing it, and the week after, in date order', () => {
  expect(weekRange('2026-12-28')).toBe('28 Dec – 3 Jan')
  const weeks = groupUpcomingWeeks([day('2027-01-04', [e('b', '2027-01-04')], 5), day('2026-12-31', [e('a', '2026-12-31')], 9), day('2027-01-02', [e('c', '2027-01-02')], 1)], '2026-12-01')
  expect(weeks.map((w) => w.label)).toEqual(['28 Dec – 3 Jan', '4–10 Jan'])
  expect(weeks[0].nets).toEqual([{ month: '2026-12', net: 9 }, { month: '2027-01', net: 1 }])
})

it('"Tue 13"', () => {
  expect(formatWeekdayDay('2026-10-13')).toBe('Tue 13')
})
