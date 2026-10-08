// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { THEME_COLORS } from '../shell/theme'

// A tiny cascade over tokens.css: which blocks apply for an OS scheme and a data-theme attribute, then the
// winning value of a token (specificity, then source order). Enough for the :root selectors tokens.css uses.
const css = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

type Block = { media: string | null; selectors: string[]; body: string; order: number }
function blocks(): Block[] {
  const out: Block[] = []
  let order = 0
  const walk = (text: string, media: string | null) => {
    const re = /([^{}]+)\{((?:[^{}]|\{[^{}]*\})*)\}/g
    for (const [, head, body] of text.matchAll(re)) {
      const h = head.trim()
      if (h.startsWith('@media')) walk(body, h)
      else out.push({ media, selectors: h.split(',').map((s) => s.trim()), body, order: order++ })
    }
  }
  walk(css, null)
  return out
}

/** Specificity of a :root selector, or null when it doesn't match <html> with this attribute. */
function match(sel: string, theme: 'light' | 'dark' | null): number | null {
  if (!sel.startsWith(':root') || sel.includes(' ')) return null
  let spec = 10 // :root is a pseudo-class
  for (const [, not, value] of sel.matchAll(/(:not\()?\[data-theme="(\w+)"\]\)?/g)) {
    const has = theme === value
    if (not ? has : !has) return null
    spec += 10
  }
  return spec
}

function token(name: string, os: 'light' | 'dark', theme: 'light' | 'dark' | null): string | undefined {
  let best: { spec: number; order: number; value: string } | undefined
  for (const b of blocks()) {
    if (b.media && !b.media.includes(`prefers-color-scheme: ${os}`)) continue
    const value = new RegExp(`--${name}:\\s*([^;]+);`).exec(b.body)?.[1]?.trim()
    if (!value) continue
    for (const sel of b.selectors) {
      const spec = match(sel, theme)
      if (spec === null) continue
      if (!best || spec > best.spec || (spec === best.spec && b.order > best.order)) best = { spec, order: b.order, value }
    }
  }
  return best?.value
}

describe('tokens honour [data-theme] over prefers-color-scheme', () => {
  it('follows the OS when there is no attribute (System)', () => {
    expect(token('bg', 'dark', null)).toBe(THEME_COLORS.dark)
    expect(token('bg', 'light', null)).toBe(THEME_COLORS.light)
  })
  it('dark tokens apply with data-theme="dark" under a light OS setting', () => {
    for (const t of ['bg', 'ink', 'surface', 'muted', 'scrim']) expect(token(t, 'light', 'dark'), t).toBe(token(t, 'dark', null))
    expect(token('bg', 'light', 'dark')).toBe(THEME_COLORS.dark)
  })
  it('light tokens apply with data-theme="light" under a dark OS setting', () => {
    for (const t of ['bg', 'ink', 'surface', 'muted', 'scrim']) expect(token(t, 'dark', 'light'), t).toBe(token(t, 'light', null))
    expect(token('bg', 'dark', 'light')).toBe(THEME_COLORS.light)
  })
  it('no other stylesheet switches on prefers-color-scheme behind the attribute’s back', () => {
    // Only tokens.css may read the OS scheme; everything else uses the tokens.
    const files = import.meta.glob('../**/*.css', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
    const offenders = Object.entries(files)
      .filter(([path, text]) => !path.endsWith('styles/tokens.css') && /prefers-color-scheme/.test(text))
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })
})
