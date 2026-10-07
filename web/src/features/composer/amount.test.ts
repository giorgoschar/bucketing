import { describe, expect, it } from 'vitest'
import {
  centsToString, convertCents, displayAmount, formatLitres, fromApiAmount, litresMilli, parseFuelPrice,
  parseRate, pressKey, toApiAmount, toCents, type AmountKey,
} from './amount'

const type = (keys: AmountKey[], from = '') => keys.reduce(pressKey, from)

describe('pressKey', () => {
  it('builds an amount and caps decimals at 2', () => {
    expect(type(['4', '.', '1', '0', '9'])).toBe('4.10')
  })
  it('one decimal point; "." first gives "0."', () => {
    expect(type(['.'])).toBe('0.')
    expect(type(['1', '.', '.', '5'])).toBe('1.5')
  })
  it('no leading zeros: "007" shows "7", "0" stays "0"', () => {
    expect(type(['0', '0', '7'])).toBe('7')
    expect(type(['0', '0'])).toBe('0')
    expect(type(['0', '.', '5'])).toBe('0.5')
  })
  it('at most 7 integer digits', () => {
    expect(type(['1', '2', '3', '4', '5', '6', '7', '8'])).toBe('1234567')
    expect(type(['9', '9', '9', '9', '9', '9', '9', '.', '9', '9'])).toBe('9999999.99')
  })
  it('backspace and clear', () => {
    expect(type(['4', '.', '1', 'back'])).toBe('4.')
    expect(type(['.', 'back'])).toBe('0')
    expect(type(['back'])).toBe('')
    expect(type(['1', '2', 'clear'])).toBe('')
  })
})

describe('cents', () => {
  it('parses keypad and API strings without floats', () => {
    expect(toCents('4.1')).toBe(410)
    expect(toCents('0.')).toBe(0)
    expect(toCents('')).toBe(0)
    expect(toCents('.')).toBe(0)
    expect(toCents('9999999.99')).toBe(999999999)
    expect(toCents('abc')).toBe(0)
  })
  it('formats for the API', () => {
    expect(centsToString(410)).toBe('4.10')
    expect(centsToString(-5)).toBe('-0.05')
    expect(toApiAmount('3')).toBe('3.00')
  })
  it('reads server numbers back into keypad strings', () => {
    expect(fromApiAmount(4.1)).toBe('4.10')
    expect(fromApiAmount(3)).toBe('3')
    expect(fromApiAmount('64.20')).toBe('64.20')
    expect(fromApiAmount(0.29)).toBe('0.29')
  })
  it('groups the integer part for display', () => {
    expect(displayAmount('')).toBe('0')
    expect(displayAmount('1234567.5')).toBe('1,234,567.5')
    expect(displayAmount('0.')).toBe('0.')
  })
})

describe('rates and fuel', () => {
  it('rate: >0, at most 1,000,000, at most 6 decimals, comma accepted', () => {
    expect(parseRate('1.153')).toBe(1_153_000n)
    expect(parseRate('1,5')).toBe(1_500_000n)
    expect(parseRate('0')).toBeNull()
    expect(parseRate('1000000')).toBe(1_000_000_000_000n)
    expect(parseRate('1000000.000001')).toBeNull()
    expect(parseRate('0.0000001')).toBeNull()
    expect(parseRate('')).toBeNull()
  })
  it('converts to household cents half-up, exactly at the extremes', () => {
    expect(convertCents(2000, parseRate('1.153')!)).toBe(2306)
    expect(convertCents(1, parseRate('0.5')!)).toBe(1) // 0.5 cent rounds up
    expect(convertCents(999_999_999, parseRate('1000000')!)).toBe(999_999_999_000_000)
  })
  it('fuel price: >0, at most 3 decimals', () => {
    expect(parseFuelPrice('1.789')).toBe(1789n)
    expect(parseFuelPrice('0')).toBeNull()
    expect(parseFuelPrice('1.7891')).toBeNull()
  })
  it('litres = amount / price, half-up to 3 decimals, as the server does', () => {
    expect(formatLitres(litresMilli(5000, 1600n))).toBe('31.25')
    expect(formatLitres(litresMilli(1000, 3000n))).toBe('3.333')
    expect(formatLitres(litresMilli(1, 4000n))).toBe('0.003') // 0.0025 rounds up
    expect(formatLitres(litresMilli(6000, 2000n))).toBe('30')
  })
})
