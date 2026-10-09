import { describe, expect, it } from 'vitest'
import { change, point } from './fixtures'
import { againstLastYear, median, twelveMonth, unitPriceOf, usualOf, yearCells, yearsOf } from './history'

const P = (due_date: string, amount: number, usage: number | null = null, entry_id = due_date) =>
  point({ entry_id, due_date, amount, usage, unit_price: usage ? Math.round((amount / usage) * 1e4) / 1e4 : null })

describe('yearCells', () => {
  const points = [P('2025-01-14', 80), P('2025-10-14', 40), P('2026-01-14', 84), P('2026-09-14', 60), P('2026-09-28', 24, null, 'x')]
  it('has twelve months for the year, with the same month a year earlier only where it exists', () => {
    const cells = yearCells(points, 2026)
    expect(cells).toHaveLength(12)
    expect(cells[0]).toMatchObject({ month: 1, amount: 84, lastYear: 80 })
    expect(cells[1]).toMatchObject({ month: 2, amount: null, lastYear: null })
    expect(cells[9]).toMatchObject({ month: 10, amount: null, lastYear: 40 })
  })
  it('sums two entries in a month', () => {
    expect(yearCells(points, 2026)[8]).toMatchObject({ month: 9, amount: 84 })
  })
  it('usage sums per month, unit price is the month total over the usage of the entries that have it', () => {
    const cells = yearCells([P('2026-03-01', 50, 100), P('2026-03-20', 30, 100), P('2026-04-01', 20)], 2026)
    expect(cells[2]).toMatchObject({ usage: 200, unitPrice: 0.4 })
    expect(cells[3]).toMatchObject({ usage: null, unitPrice: null })
  })
})

it('yearsOf lists the years with entries, oldest first', () => {
  expect(yearsOf([P('2026-01-01', 1), P('2024-05-01', 1), P('2026-02-01', 1)])).toEqual([2024, 2026])
  expect(yearsOf([])).toEqual([])
})

describe('againstLastYear', () => {
  const points = [P('2025-01-14', 80), P('2026-01-14', 84), P('2026-02-14', 50), P('2025-03-01', 0), P('2026-03-01', 10)]
  it('is the difference in € and whole %', () => {
    expect(againstLastYear(points, points[1])).toEqual({ delta: 4, pct: 5 })
  })
  it('is null when last year has no entry for that month', () => {
    expect(againstLastYear(points, points[2])).toBeNull()
  })
  it('keeps the euros and drops the percent when last year was 0', () => {
    expect(againstLastYear(points, points[4])).toEqual({ delta: 10, pct: null })
  })
  it('rounds half up', () => {
    const p = [P('2025-05-01', 200), P('2026-05-01', 205)]
    expect(againstLastYear(p, p[1])).toEqual({ delta: 5, pct: 3 })
    const d = [P('2025-05-01', 200), P('2026-05-01', 190)]
    expect(againstLastYear(d, d[1])).toEqual({ delta: -10, pct: -5 })
  })
})

describe('usualOf', () => {
  it('is the change usual when there is one', () => {
    expect(usualOf([P('2026-01-01', 1)], change({ usual: 61 }))).toBe(61)
  })
  it('falls back to the median of the last 3', () => {
    const pts = [P('2026-01-01', 500), P('2026-02-01', 10), P('2026-03-01', 30), P('2026-04-01', 20)]
    expect(usualOf(pts, null)).toBe(20)
  })
  it('is null without points', () => expect(usualOf([], null)).toBeNull())
  it('median of an even count is the mean of the middle two', () => expect(median([1, 3])).toBe(2))
})

describe('twelveMonth', () => {
  const today = '2026-10-09'
  it('sums the entries in the 12 calendar months ending this month and divides by their number', () => {
    const pts = [P('2025-09-30', 999), P('2025-10-31', 999), P('2025-11-01', 40), P('2026-05-01', 60), P('2026-10-31', 20)]
    expect(twelveMonth(pts, today)).toEqual({ total: 120, average: 40 })
  })
  it('is null with none', () => expect(twelveMonth([P('2024-01-01', 5)], today)).toBeNull())
})

it('unitPriceOf is amount over usage to 4 places, null without usage or with 0', () => {
  expect(unitPriceOf(84, 412)).toBe(0.2039)
  expect(unitPriceOf(84, 0)).toBeNull()
  expect(unitPriceOf(84, null)).toBeNull()
})
