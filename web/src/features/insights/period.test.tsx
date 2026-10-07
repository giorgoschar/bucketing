import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  PERIOD_STORAGE_KEY,
  parsePeriod,
  periodKey,
  periodQuery,
  previousPeriod,
  rangeError,
  usePeriod,
  writePeriod,
} from './period'

afterEach(cleanup)

/** Node 26 ships a half-working global `localStorage` that shadows jsdom's; use a plain in-memory one. */
function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    get length() { return m.size },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  }
}
beforeEach(() => { vi.stubGlobal('localStorage', memoryStorage()) })
afterEach(() => { vi.unstubAllGlobals() })

const q = (s: string) => new URLSearchParams(s)

describe('parsePeriod', () => {
  it('reads presets and valid custom ranges', () => {
    expect(parsePeriod(q('p=last_3m'))).toEqual({ preset: 'last_3m' })
    expect(parsePeriod(q('p=custom&from=2026-09-01&to=2026-09-30'))).toEqual({
      preset: 'custom', from: '2026-09-01', to: '2026-09-30',
    })
  })
  it('rejects junk, From after To and malformed dates', () => {
    expect(parsePeriod(q(''))).toBeNull()
    expect(parsePeriod(q('p=all_time'))).toBeNull()
    expect(parsePeriod(q('p=custom&from=2026-10-06&to=2026-10-01'))).toBeNull()
    expect(parsePeriod(q('p=custom&from=2026-02-30&to=2026-03-01'))).toBeNull()
    expect(parsePeriod(q('p=custom&from=2026-10-01'))).toBeNull()
  })
})

describe('helpers', () => {
  it('writes and clears from/to', () => {
    const custom = writePeriod(q('lens=u1'), { preset: 'custom', from: '2026-09-01', to: '2026-09-02' })
    expect(custom.toString()).toBe('lens=u1&p=custom&from=2026-09-01&to=2026-09-02')
    expect(writePeriod(custom, { preset: 'this_year' }).toString()).toBe('lens=u1&p=this_year')
  })
  it('maps to the API query and a cache key', () => {
    expect(periodQuery({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' })).toEqual({
      preset: 'custom', start_date: '2026-09-01', end_date: '2026-09-30',
    })
    expect(periodKey({ preset: 'last_month' })).toBe('last_month')
    expect(periodKey({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' })).toBe('custom:2026-09-01:2026-09-30')
  })
  it('explains range errors', () => {
    expect(rangeError('', '2026-10-01')).toBe('Pick both dates.')
    expect(rangeError('2026-10-02', '2026-10-01')).toBe('From must be on or before To.')
    expect(rangeError('2026-10-01', '2026-10-01')).toBeNull()
  })
  it('finds the previous period', () => {
    expect(previousPeriod({ preset: 'this_month' }, '2026-10-01', '2026-10-06')).toEqual({ preset: 'last_month' })
    expect(previousPeriod({ preset: 'last_3m' }, '2026-07-01', '2026-10-06')).toEqual({
      preset: 'custom', from: '2026-03-25', to: '2026-06-30',
    })
    expect(previousPeriod({ preset: 'this_year' }, null, null)).toBeNull()
  })
})

function wrapper(initial: string) {
  return ({ children }: { children: ReactNode }) => <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
}

describe('usePeriod', () => {
  afterEach(() => localStorage.clear())

  it('URL wins, then storage, then this_month', () => {
    localStorage.setItem(PERIOD_STORAGE_KEY, JSON.stringify({ preset: 'last_6m' }))
    expect(renderHook(() => usePeriod(), { wrapper: wrapper('/insights?p=last_month') }).result.current[0])
      .toEqual({ preset: 'last_month' })
    expect(renderHook(() => usePeriod(), { wrapper: wrapper('/insights') }).result.current[0])
      .toEqual({ preset: 'last_6m' })
    localStorage.setItem(PERIOD_STORAGE_KEY, '{not json')
    expect(renderHook(() => usePeriod(), { wrapper: wrapper('/insights') }).result.current[0])
      .toEqual({ preset: 'this_month' })
  })

  it('setting writes the URL and storage (round trip)', () => {
    const { result } = renderHook(() => ({ p: usePeriod(), loc: useLocation() }), { wrapper: wrapper('/insights') })
    act(() => result.current.p[1]({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' }))
    expect(result.current.loc.search).toBe('?p=custom&from=2026-09-01&to=2026-09-30')
    expect(result.current.p[0]).toEqual({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' })
    expect(JSON.parse(localStorage.getItem(PERIOD_STORAGE_KEY)!)).toEqual(result.current.p[0])
  })
})
