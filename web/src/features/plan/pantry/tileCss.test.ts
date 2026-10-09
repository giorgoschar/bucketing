// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const pantry = readFileSync(new URL('./pantry.css', import.meta.url), 'utf8')
const tokens = readFileSync(new URL('../../../styles/tokens.css', import.meta.url), 'utf8')

type RGB = [number, number, number]
const hex = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as RGB
const mix = (a: RGB, b: RGB, p: number): RGB => a.map((v, i) => v * p + b[i] * (1 - p)) as RGB
const lum = (c: RGB) => {
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contrast = (a: RGB, b: RGB) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** A token block's declarations: the dark :root, and the light theme's [data-theme="light"]. */
function theme(selector: string) {
  const start = tokens.indexOf(`${selector} {`)
  const block = tokens.slice(start, tokens.indexOf('\n}', start))
  const get = (name: string) => hex(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`).exec(block)![1])
  return { surface: get('surface'), ink: get('ink'), tints: [1, 2, 3, 4, 5, 6].map((n) => get(`c${n}`)) }
}

// Pantry review M-4: the letter on a pantry tile was 2.3–3.6:1 in light mode.
it('the pantry tile letter is at least 4.5:1 on its tile for every tint, light and dark', () => {
  const rule = /\.pantry-tile \{([^}]*)\}/.exec(pantry)![1]
  const bg = Number(/background: color-mix\(in srgb, var\(--tint, var\(--c6\)\) (\d+)%, var\(--surface\)\)/.exec(rule)![1]) / 100
  const fg = Number(/[^-]color: color-mix\(in srgb, var\(--tint, var\(--c6\)\) (\d+)%, var\(--ink\)\)/.exec(rule)![1]) / 100
  for (const t of [theme(':root'), theme(':root[data-theme="light"]')]) {
    for (const tint of t.tints) {
      expect(contrast(mix(tint, t.ink, fg), mix(tint, t.surface, bg))).toBeGreaterThanOrEqual(4.5)
    }
  }
})

// Fix round 1 (review M-6): at 390 px each of the two price buttons is about 160 px wide; .btn is nowrap, so
// "Refresh prices" would spill past its border with a larger system font.
it('the Prices today buttons let their label wrap inside the button', () => {
  const rule = /\.pantry-card__acts \.btn \{([^}]*)\}/.exec(pantry)![1]
  expect(rule).toMatch(/white-space:\s*normal/)
  expect(rule).toMatch(/min-width:\s*0/)
  expect(rule).toMatch(/min-height:\s*4[4-9]px/)
  expect(rule).toMatch(/height:\s*auto/)
})
