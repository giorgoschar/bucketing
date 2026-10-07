import { afterEach, beforeEach, vi } from 'vitest'

/** Node 26 ships a half-working global `localStorage` that shadows jsdom's; use a plain in-memory one. */
export function memoryStorage(): Storage {
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

/** Call at the top of a test file: a fresh in-memory localStorage for every test. */
export function installMemoryStorage(): void {
  beforeEach(() => { vi.stubGlobal('localStorage', memoryStorage()) })
  afterEach(() => { vi.unstubAllGlobals() })
}
