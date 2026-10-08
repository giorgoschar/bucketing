import { useSyncExternalStore } from 'react'

export const isOnline = (): boolean => globalThis.navigator?.onLine !== false

const subscribe = (cb: () => void) => {
  window.addEventListener('online', cb)
  window.addEventListener('offline', cb)
  return () => {
    window.removeEventListener('online', cb)
    window.removeEventListener('offline', cb)
  }
}

/** The browser's online flag, live. Optimistic: a captive portal still counts as online. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, isOnline, () => true)
}
