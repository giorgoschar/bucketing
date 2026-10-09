import { expect, it } from 'vitest'
import { change } from './fixtures'
import { changeBody, changeLabel, changeSentence, changeTitle, moneyShort } from './format'

it('moneyShort drops .00 and keeps cents', () => {
  expect(moneyShort(84)).toBe('€84')
  expect(moneyShort(84.5)).toBe('€84.50')
  expect(moneyShort(61.234)).toBe('€61.23')
})

it('the label has an arrow and words, rounded to a whole percent', () => {
  expect(changeLabel(change({ pct: 37.7 }))).toBe('↑ 38% vs usual')
  expect(changeLabel(change({ pct: -22.2, direction: 'down' }))).toBe('↓ 22% vs usual')
})

it('the title and the body for each case of spec §3.7', () => {
  const c = change()
  expect(changeTitle('Electricity', c)).toBe('Electricity was €84, usually €61')
  expect(changeBody(c, 'kWh')).toBe('Usual from the last 3 payments: €61.')
  expect(changeBody(change({ basis: 'last_year' }), 'kWh')).toBe('Same month last year: €61.')
  expect(changeBody(change({ reason: 'usage', reason_pct: 30 }), 'kWh')).toBe('Usual from the last 3 payments: €61. You used 30% more kWh.')
  expect(changeBody(change({ reason: 'usage', reason_pct: -12 }), 'kWh')).toContain('You used 12% less kWh.')
  expect(changeBody(change({ reason: 'price', reason_pct: 12 }), 'kWh')).toContain('The price per kWh went up 12%.')
  expect(changeBody(change({ reason: 'price', reason_pct: -12 }), 'kWh')).toContain('The price per kWh went down 12%.')
  expect(changeSentence('Electricity', change({ basis: 'last_year', reason: 'usage', reason_pct: 30 }), 'kWh'))
    .toBe('Electricity was €84, usually €61. Same month last year: €61. You used 30% more kWh.')
})
