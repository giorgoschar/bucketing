/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(`${process.cwd()}/src/styles/tokens.css`, 'utf8')

// The manual P1 pass measured muted text at 4.35:1 on the light page and 4.01:1 on the segmented control.

function lum(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const f = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
const ratio = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}
/** Every block that sets --muted, with the backgrounds it sets next to it. */
function themes(): Record<string, string>[] {
  return [...css.matchAll(/\{([^{}]*--muted:[^{}]*)\}/g)].map(([, body]) =>
    Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9A-Fa-f]{6})/g)].map(([, k, v]) => [k, v])))
}

it('muted text meets WCAG AA (4.5:1) on the page, cards and the segmented control, in every theme', () => {
  const all = themes()
  expect(all.length).toBeGreaterThanOrEqual(3) // dark, light by preference, light by choice
  for (const t of all) {
    for (const bg of ['bg', 'surface', 'surface-2']) {
      expect(ratio(t.muted, t[bg]), `--muted ${t.muted} on --${bg} ${t[bg]}`).toBeGreaterThanOrEqual(4.5)
    }
  }
})
