import { describe, expect, it } from 'vitest'
import { amountShares, equalShares, ownShares, percentShares, splitProblem, toShareList, typedFromShares } from './splits'

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
