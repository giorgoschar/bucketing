import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DESKTOP_QUERY, useIsDesktop } from './useIsDesktop'

function Probe() {
  return <p>{useIsDesktop() ? 'desktop' : 'phone'}</p>
}

/** A matchMedia whose answer the test can flip. Reusable: `const mq = stubDesktop(true)`. */
function stubMatchMedia(initial: boolean) {
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

afterEach(() => vi.unstubAllGlobals())

it('is phone without matchMedia', () => {
  vi.stubGlobal('matchMedia', undefined)
  render(<Probe />)
  expect(screen.getByText('phone')).toBeInTheDocument()
})

it('follows the 1024 px query as the window is resized', () => {
  const mq = stubMatchMedia(true)
  render(<Probe />)
  expect(screen.getByText('desktop')).toBeInTheDocument()
  act(() => mq.set(false))
  expect(screen.getByText('phone')).toBeInTheDocument()
})
