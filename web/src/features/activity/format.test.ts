
import { describe, expect, it } from 'vitest'
import { dayLabel, gapLabel, groupByDay } from './format'
import type { Txn } from './hooks'

const TODAY = new Date(2026, 9, 6)
const row = (id: string, date: string, created: string) =>
  ({ id, transaction_date: date, created_at: created }) as unknown as Txn

describe('format', () => {
  it('labels days like the mock', () => {
    expect(dayLabel('2026-10-06', TODAY)).toBe('Today · Tue 6 Oct')
    expect(dayLabel('2026-10-05', TODAY)).toBe('Yesterday · Mon 5 Oct')
    expect(dayLabel('2026-10-01', TODAY)).toBe('Thu 1 Oct')
    expect(dayLabel('2025-12-24', TODAY)).toBe('Wed 24 Dec 2025')
  })

  it('groups rows by day with the server net', () => {
    const groups = groupByDay(
      [row('a', '2026-10-06', '2026-10-06T09:00:00'), row('b', '2026-10-06', '2026-10-06T08:00:00'), row('c', '2026-10-05', '2026-10-05T08:00:00')],
      { '2026-10-06': 85, '2026-10-05': -7 },
    )
    expect(groups.map((g) => [g.date, g.net, g.rows.map((r) => r.id)])).toEqual([
      ['2026-10-06', 85, ['a', 'b']],
      ['2026-10-05', -7, ['c']],
    ])
  })

  it('shows minutes for pairs created ≤10 min apart, else days', () => {
    expect(gapLabel(row('a', '2026-10-06', '2026-10-06T09:00:00'), row('b', '2026-10-06', '2026-10-06T09:02:10'))).toBe('2 min apart')
    expect(gapLabel(row('a', '2026-10-03', '2026-10-03T09:00:00'), row('b', '2026-10-06', '2026-10-06T09:00:00'))).toBe('3 days apart')
    expect(gapLabel(row('a', '2026-10-06', '2026-10-06T09:00:00'), row('b', '2026-10-06', '2026-10-06T18:00:00'))).toBe('Same day')
  })
})
