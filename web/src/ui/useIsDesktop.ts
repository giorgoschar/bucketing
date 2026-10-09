import { useSyncExternalStore } from 'react'

/** The one desktop breakpoint (Phase A spec §4.1). CSS uses the same value: `@media (min-width: 1024px)`. */
export const DESKTOP_QUERY = '(min-width: 1024px)'

const list = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(DESKTOP_QUERY) : null)

function subscribe(onChange: () => void) {
  const mql = list()
  if (!mql) return () => {}
  mql.addEventListener('change', onChange)
  return () => mql.removeEventListener('change', onChange)
}

/** True on a viewport at least 1024 px wide; follows resizes. False where matchMedia is missing (tests, old browsers). */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, () => list()?.matches ?? false, () => false)
}
