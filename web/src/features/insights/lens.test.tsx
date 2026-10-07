import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HOUSEHOLD, LENS_STORAGE_KEY, insightsSearch, lensOptions, lensQuery, resolveLens, useLens } from './lens'

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

const members = [
  { user_id: 'me', display_name: 'Giorgos Charitidis', username: 'giorgos' },
  { user_id: 'm', display_name: 'Maria Papadopoulou', username: 'maria' },
  { user_id: 'k', display_name: 'Kostas A', username: 'kostas1' },
  { user_id: 'k2', display_name: 'Kostas B', username: 'kostas2' },
]

describe('lensOptions', () => {
  it('is Household, Me, then others by first name; duplicate first names use full names', () => {
    expect(lensOptions(members, 'me')).toEqual([
      { value: HOUSEHOLD, label: 'Household' },
      { value: 'me', label: 'Me' },
      { value: 'k', label: 'Kostas A' },
      { value: 'k2', label: 'Kostas B' },
      { value: 'm', label: 'Maria' },
    ])
  })
})

describe('resolveLens', () => {
  it('falls back to Household for a member who left', () => {
    expect(resolveLens('gone', members)).toBe(HOUSEHOLD)
    expect(resolveLens('m', members)).toBe('m')
    expect(resolveLens(null, members)).toBe(HOUSEHOLD)
    expect(resolveLens('m', undefined)).toBe('m') // members not loaded yet: trust it
  })
  it('maps to paid_by', () => {
    expect(lensQuery(HOUSEHOLD)).toEqual({})
    expect(lensQuery('m')).toEqual({ paid_by: 'm' })
  })
  it('builds drill-down search strings', () => {
    expect(insightsSearch({ preset: 'last_month' }, 'm')).toBe('?p=last_month&lens=m')
    expect(insightsSearch({ preset: 'this_month' }, HOUSEHOLD)).toBe('?p=this_month')
  })
})

describe('useLens', () => {
  afterEach(() => localStorage.clear())
  const wrapper = (initial: string) => ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
  )

  it('reads URL, then storage, and writes both', () => {
    localStorage.setItem(LENS_STORAGE_KEY, 'm')
    const { result } = renderHook(() => ({ l: useLens(members), loc: useLocation() }), { wrapper: wrapper('/insights') })
    expect(result.current.l[0]).toBe('m')
    act(() => result.current.l[1]('k'))
    expect(result.current.loc.search).toBe('?lens=k')
    expect(localStorage.getItem(LENS_STORAGE_KEY)).toBe('k')
    act(() => result.current.l[1](HOUSEHOLD))
    expect(result.current.loc.search).toBe('')
  })
})
