import { vi } from 'vitest'
import { DESKTOP_QUERY } from '../ui/useIsDesktop'

/** Test helper: a `matchMedia` whose desktop answer the test can flip, as `useIsDesktop` reads it.
 *  `const mq = stubDesktop(true)`, later `act(() => mq.set(false))`. Undo with `vi.unstubAllGlobals()`. */
export function stubDesktop(initial: boolean) {
  let matches = initial
  const listeners = new Set<() => void>()
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() { return query === DESKTOP_QUERY && matches },
    media: query,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }))
  return { set(next: boolean) { matches = next; listeners.forEach((fn) => fn()) } }
}
