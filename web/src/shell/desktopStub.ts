import { vi } from 'vitest'
import { DESKTOP_QUERY } from '../ui/useIsDesktop'

/** Test helper: a `matchMedia` whose desktop answer the test can flip, as `useIsDesktop` reads it.
 *  `const mq = stubDesktop(true)`, later `await act(() => mq.set(false))`. Undo with `vi.unstubAllGlobals()`.
 *  Like a browser, `set` fires the listeners one at a time in the order they were added and lets pending
 *  work (React's re-render, an unmount) finish between them, so a listener added later may never run. */
export function stubDesktop(initial: boolean) {
  let matches = initial
  const listeners = new Set<() => void>()
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() { return query === DESKTOP_QUERY && matches },
    media: query,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }))
  return {
    async set(next: boolean) {
      matches = next
      for (const fn of [...listeners]) {
        if (!listeners.has(fn)) continue // removed by an unmount while an earlier listener ran
        fn()
        await new Promise((r) => setTimeout(r, 0))
      }
    },
  }
}
