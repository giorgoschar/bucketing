import { describe, expect, it } from 'vitest'
import { amountShares, invalidInputs, equalShares, ownShares, percentShares, splitProblem, toShareList, typedFromShares } from './splits'

const sum = (m: Record<string, number>) => Object.values(m).reduce((a, x) => a + x, 0)

describe('equal (the server equal_split rule)', () => {
  it('rounds down to the cent; leftover cents go to the payer', () => {
    const s = equalShares(1000, ['u3', 'u1', 'u2'], 'u2')
    expect(s).toEqual({ u1: 333, u2: 334, u3: 333 })
    expect(sum(s)).toBe(1000)
  })
  it('a payer outside the members: the first id in order takes them', () => {
    expect(equalShares(1001, ['u2', 'u1'], 'zz')).toEqual({ u1: 501, u2: 500 })
  })
})

describe('amounts and percent: the payer takes the remainder', () => {
  it('amounts', () => {
    expect(amountShares(1000, ['u1', 'u2'], 'u1', { u2: '3.50' })).toEqual({ u1: 650, u2: 350 })
    expect(splitProblem(1000, amountShares(1000, ['u1', 'u2'], 'u1', { u2: '12' }), false)).toBe('negative')
  })
  it('percent rounds each share down to the cent and still sums to the total', () => {
    const s = percentShares(1000, ['u1', 'u2', 'u3'], 'u1', { u2: '33.33', u3: '33.33' })
    expect(s).toEqual({ u1: 334, u2: 333, u3: 333 })
    expect(sum(s)).toBe(1000)
    expect(splitProblem(1000, percentShares(1000, ['u1', 'u2'], 'u1', { u2: '120' }), false)).toBe('negative')
  })
})

describe('own share', () => {
  it('everyone types; must add up to the total within a cent', () => {
    expect(splitProblem(1000, ownShares(['u1', 'u2'], { u1: '6', u2: '4' }), true)).toBeNull()
    expect(splitProblem(1000, ownShares(['u1', 'u2'], { u1: '6', u2: '3.99' }), true)).toBeNull()
    expect(splitProblem(1000, ownShares(['u1', 'u2'], { u1: '6', u2: '3' }), true)).toBe('mismatch')
  })
})

it('to and from the API list, in member order, every member present', () => {
  const list = toShareList(['u1', 'u2'], { u2: 350, u1: 650 })
  expect(list).toEqual([{ user_id: 'u1', amount: '6.50' }, { user_id: 'u2', amount: '3.50' }])
  expect(typedFromShares(list)).toEqual({ u1: '6.50', u2: '3.50' })
})

describe('typed inputs parse one way in every mode', () => {
  it('a comma decimal counts in amounts, percent and own share', () => {
    expect(amountShares(2000, ['u1', 'u2'], 'u1', { u2: '12,50' })).toEqual({ u1: 750, u2: 1250 })
    expect(percentShares(1000, ['u1', 'u2'], 'u1', { u2: '12,5' })).toEqual({ u1: 875, u2: 125 })
    expect(ownShares(['u1', 'u2'], { u1: '6,50', u2: '3,50' })).toEqual({ u1: 650, u2: 350 })
  })
  it('malformed text is reported, never read as 0', () => {
    expect(invalidInputs({ u1: '1.234', u2: '3', u3: '' }, 'amount')).toEqual(['u1'])
    expect(invalidInputs({ u1: 'abc', u2: '12,345', u3: '10' }, 'percent')).toEqual(['u1', 'u2'])
  })
})
