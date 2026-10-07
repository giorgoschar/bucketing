import { describe, expect, it } from 'vitest'
import {
  addDays, formatDayHeader, formatMoney, formatMonthLabel, formatMonthName, formatMonthShort,
  formatShortDate, formatTime, monthsBetween, ordinal, parseAmount, shiftMonth, todayISO,
} from './format'

describe('formatMoney', () => {
  it('formats euros with a real minus and an optional plus', () => {
    expect(formatMoney(1284.6)).toBe('€1,284.60')
    expect(formatMoney(-64.2)).toBe('−€64.20')
    expect(formatMoney(1865, { signed: true })).toBe('+€1,865.00')
    expect(formatMoney(0, { signed: true })).toBe('€0.00')
    expect(formatMoney(1200, { whole: true })).toBe('€1,200')
    expect(formatMoney(-0.001)).toBe('€0.00')
  })
  it('handles other currencies and a bad code without throwing', () => {
    expect(formatMoney(12.5, { currency: 'USD' })).toBe('US$12.50')
    expect(formatMoney(12.5, { currency: 'eu' })).toBe('12.50 eu')
  })
})

describe('parseAmount', () => {
  it('accepts a comma or a dot and returns two decimals', () => {
    expect(parseAmount('86,40')).toBe('86.40')
    expect(parseAmount('86,4')).toBe('86.40')
    expect(parseAmount(' 1500 ')).toBe('1500.00')
    expect(parseAmount('€38.9')).toBe('38.90')
    expect(parseAmount('.5')).toBe('0.50')
  })
  it('blank is null; anything else is undefined', () => {
    expect(parseAmount('')).toBeNull()
    expect(parseAmount('   ')).toBeNull()
    expect(parseAmount('abc')).toBeUndefined()
    expect(parseAmount('1.234,50')).toBeUndefined()
    expect(parseAmount('-5')).toBeUndefined()
    expect(parseAmount('3.456')).toBeUndefined()
  })
})

describe('dates', () => {
  it('formats local dates the way the screens show them', () => {
    expect(formatDayHeader('2026-10-26')).toBe('Mon 26 Oct')
    expect(formatShortDate('2026-10-09')).toBe('9 Oct')
    expect(formatMonthLabel('2026-10')).toBe('Oct 2026')
    expect(formatMonthShort('2027-01')).toBe('Jan')
    expect(formatMonthName(12)).toBe('December')
    expect(formatTime(new Date(2026, 9, 7, 14, 2).getTime())).toBe('14:02')
  })
  it('does date arithmetic across month and year ends', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
    expect(monthsBetween('2026-10', '2027-09')).toBe(11)
    expect(monthsBetween('2026-10', '2025-11')).toBe(-11)
    expect(todayISO(new Date(2026, 9, 7, 23, 59))).toBe('2026-10-07')
  })
  it('ordinals', () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 26, 31].map(ordinal)).toEqual([
      '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '26th', '31st',
    ])
  })
})
