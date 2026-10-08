import { describe, expect, it } from 'vitest'
import { OFF, expectedCount, isSelected, reduce, selectedCount, toSelect } from './selection'

const OCT = { from_date: '2026-10-01', to_date: '2026-10-31' }

describe('selection', () => {
  it('All → by filter → untick → hand-picked', () => {
    let s = reduce(OFF, { type: 'enter', id: 'a' })
    expect(toSelect(s)).toEqual({ ids: ['a'] })
    s = reduce(s, { type: 'all', filter: { missing_payer: true, ...OCT }, total: 120 })
    expect(s.kind).toBe('filter')
    expect(selectedCount(s)).toBe(120)
    expect(isSelected(s, 'anything')).toBe(true)
    expect(toSelect(s)).toEqual({ filter: { missing_payer: true, ...OCT } })
    expect(expectedCount(s)).toBe(120)
    s = reduce(s, { type: 'toggle', id: 'b', loadedIds: ['a', 'b', 'c'] })
    expect(s).toEqual({ kind: 'picked', ids: ['a', 'c'] })
    expect(expectedCount(s)).toBeNull()
  })

  it('All with only a bill filter selects by bill', () => {
    const s = reduce(reduce(OFF, { type: 'enter' }), { type: 'all', filter: { recurring_bill_id: 'r1' }, total: 14 })
    expect(toSelect(s)).toEqual({ bill_id: 'r1' })
    expect(expectedCount(s)).toBe(14)
  })

  it('a bill plus anything else stays by filter', () => {
    const s = reduce(OFF, { type: 'all', filter: { recurring_bill_id: 'r1', ...OCT }, total: 1 })
    expect(s.kind).toBe('filter')
  })

  it('toggling picks and unpicks; cancel leaves selection', () => {
    let s = reduce(OFF, { type: 'toggle', id: 'a', loadedIds: [] })
    s = reduce(s, { type: 'toggle', id: 'b', loadedIds: [] })
    s = reduce(s, { type: 'toggle', id: 'a', loadedIds: [] })
    expect(toSelect(s)).toEqual({ ids: ['b'] })
    expect(reduce(s, { type: 'cancel' })).toEqual(OFF)
  })
})
