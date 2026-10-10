import { describe, expect, it } from 'vitest'
import {
  comparison, dayAndMonth, daysLeftText, doneNote, monthBounds, monthTitle, ofBudget, overText, reviewDeadline, short, stateLine, usuallyText,
} from './sentences'

const base = { month: '2026-09', reviewed_at: null, closed: false, days_left: 3 }

describe('stateLine', () => {
  it('in the review window and not reviewed: the deadline and the days left', () => {
    expect(stateLine(base)).toBe('Review by 5 October · 3 days left')
    expect(stateLine({ ...base, days_left: 1 })).toBe('Review by 5 October · 1 day left')
  })
  it('December is reviewed by 5 January', () => {
    expect(stateLine({ ...base, month: '2026-12', days_left: 3 })).toBe('Review by 5 January · 3 days left')
  })
  it('reviewed: the date, and by you, by a name, or by nobody', () => {
    const r = { ...base, reviewed_at: '2026-10-02T09:30:00', closed: true, days_left: null }
    expect(stateLine(r, { kind: 'you' })).toBe('Reviewed on 2 October by you')
    expect(stateLine(r, { kind: 'name', name: 'Giorgos' })).toBe('Reviewed on 2 October by Giorgos')
    expect(stateLine(r, { kind: 'none' })).toBe('Reviewed on 2 October')
    expect(stateLine(r)).toBe('Reviewed on 2 October')
  })
  it('closed without a review', () => {
    expect(stateLine({ ...base, closed: true, days_left: null })).toBe('Closed automatically')
  })
  it('reviewed wins over closed', () => {
    expect(stateLine({ ...base, reviewed_at: '2026-10-07T00:00:00', closed: true, days_left: null })).toBe('Reviewed on 7 October')
  })
})

describe('comparison with the month before', () => {
  it('more, less and equal, in words', () => {
    expect(comparison(2240, 2000, '2026-08')).toBe('€240 more than August')
    expect(comparison(760, 1000, '2026-08')).toBe('€240 less than August')
    expect(comparison(3000, 3000, '2026-08')).toBe('Same as August')
  })
  it('keeps the cents when there are some', () => {
    expect(comparison(10.5, 10, '2026-02')).toBe('€0.50 more than February')
  })
  it('a negative net against a positive one', () => {
    expect(comparison(-200, 1000, '2026-08')).toBe('€1,200 less than August')
  })
  it('across the turn of the year it names December', () => {
    expect(comparison(100, 50, '2025-12')).toBe('€50 more than December')
  })
})

it('"€110 over", "€1,310 of €1,200" and "usually €240"', () => {
  expect(overText(110)).toBe('€110 over')
  expect(overText(110.4)).toBe('€110.40 over')
  expect(ofBudget(1310, 1200)).toBe('€1,310 of €1,200')
  expect(usuallyText(240)).toBe('usually €240')
})

it('short money: whole when whole, a real minus', () => {
  expect(short(84)).toBe('€84')
  expect(short(84.5)).toBe('€84.50')
  expect(short(-12)).toBe('−€12')
  expect(short(0)).toBe('€0')
})

it('days-left plural', () => {
  expect(daysLeftText(1)).toBe('1 day left')
  expect(daysLeftText(5)).toBe('5 days left')
})

it('names the month', () => {
  expect(doneNote('2026-09')).toBe('Marks September as reviewed for the whole household.')
  expect(monthTitle('2026-09')).toBe('September 2026')
  expect(monthTitle('nope')).toBe('Statement')
  expect(reviewDeadline('2026-09')).toBe('5 October')
  expect(dayAndMonth('2026-10-02T09:30:00')).toBe('2 October')
  expect(monthBounds('2026-02')).toEqual({ from: '2026-02-01', to: '2026-02-28' })
})
