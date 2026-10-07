import { afterEach, expect, it } from 'vitest'
import { addDays, dayLabel, rangeLabel, shortDate, todayLocal } from './dates'

const TZ = process.env.TZ
afterEach(() => { process.env.TZ = TZ })

it('todayLocal is the device calendar day, not the UTC one (Athens just after midnight)', () => {
  process.env.TZ = 'Europe/Athens'
  // 22:30 UTC on 7 Oct is 01:30 on 8 Oct in Athens (UTC+3 in October).
  expect(todayLocal(new Date('2026-10-07T22:30:00Z'))).toBe('2026-10-08')
})

it('addDays crosses months and years in local time', () => {
  expect(addDays('2026-10-01', -1)).toBe('2026-09-30')
  expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
})

it('labels', () => {
  expect(dayLabel('2026-10-07', '2026-10-07')).toBe('Today')
  expect(dayLabel('2026-10-06', '2026-10-07')).toBe('Yesterday')
  expect(dayLabel('2026-10-05', '2026-10-07')).toBe('Mon 5 Oct')
  expect(shortDate('2026-10-07')).toBe('7 Oct')
  expect(rangeLabel('2026-08-12', '2026-08-19')).toBe('12–19 Aug')
  expect(rangeLabel('2026-09-30', '2026-10-02')).toBe('30 Sep – 2 Oct')
  expect(rangeLabel(null, null)).toBe('')
})
