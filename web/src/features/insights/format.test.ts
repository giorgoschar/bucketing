import { describe, expect, it } from 'vitest'
import { dayRange, eur, eurWhole, monthEnd, pctText } from './format'

describe('format', () => {
  it('formats euros', () => {
    expect(eur(1284.6)).toBe('€1,284.60')
    expect(eur(-3)).toBe('−€3.00')
    expect(eurWhole(2310.4)).toBe('€2,310')
    expect(pctText(-8)).toBe('8%')
  })
  it('formats ranges', () => {
    expect(dayRange('2026-10-01', '2026-10-06')).toBe('Oct 1 – 6')
    expect(dayRange('2026-09-03', '2026-10-06')).toBe('Sep 3 – Oct 6')
    expect(dayRange(null, null)).toBe('All time')
    expect(monthEnd('2026-02-10')).toBe('Feb 28')
  })
})
