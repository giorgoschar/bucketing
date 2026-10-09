import { describe, expect, it } from 'vitest'
import { BULK_MAX_ROWS, allMode } from './selection'

// Polish A4 (P3 M1) and review M-7: what "All" does, given what the list knows.
describe('allMode', () => {
  const base = { total: 120, selectable: 50, excluded: 0, complete: false, pending: false, emptyFilter: false }
  it('nothing pending: the filter on the server, with the server count', () => {
    expect(allMode(base)).toEqual({ kind: 'filter', count: 120 })
  })
  it('a loaded row is pending and every row is loaded: the selectable rows by id', () => {
    expect(allMode({ ...base, total: 50, selectable: 48, excluded: 2, complete: true, pending: true })).toEqual({ kind: 'ids', count: 48 })
  })
  it('by id needs no filter (ids are explicit), a filter selection does', () => {
    expect(allMode({ ...base, total: 3, selectable: 2, excluded: 1, complete: true, pending: true, emptyFilter: true })).toEqual({ kind: 'ids', count: 2 })
    expect(allMode({ ...base, emptyFilter: true })).toEqual({ kind: 'off', reason: null })
  })
  it('something pending and more to load: off, until the sync', () => {
    expect(allMode({ ...base, pending: true })).toEqual({ kind: 'off', reason: 'pending' })
  })
  it('by id is capped at the server’s bulk limit', () => {
    expect(BULK_MAX_ROWS).toBe(1000) // app/services/bulk.py BULK_MAX_ROWS
    const many = { ...base, total: 1002, excluded: 1, complete: true, pending: true }
    expect(allMode({ ...many, selectable: 1000 })).toEqual({ kind: 'ids', count: 1000 })
    expect(allMode({ ...many, total: 1003, selectable: 1001 })).toEqual({ kind: 'off', reason: 'too-many' })
  })
  it('by filter is capped too: more than 1,000 matches is off (the server answers 400)', () => {
    expect(allMode({ ...base, total: 1000 })).toEqual({ kind: 'filter', count: 1000 })
    expect(allMode({ ...base, total: 1001 })).toEqual({ kind: 'off', reason: 'too-many' })
    // No filter at all: off for its own reason, not a "narrow the filter" one.
    expect(allMode({ ...base, total: 5000, emptyFilter: true })).toEqual({ kind: 'off', reason: null })
  })
  it('nothing to select: off', () => {
    expect(allMode({ ...base, total: 0, selectable: 0, complete: true })).toEqual({ kind: 'off', reason: null })
    expect(allMode({ ...base, total: 1, selectable: 0, excluded: 1, complete: true, pending: true })).toEqual({ kind: 'off', reason: null })
  })
})
