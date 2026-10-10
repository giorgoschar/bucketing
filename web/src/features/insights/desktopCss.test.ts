// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

/** The CSS with every @media block removed: what the phone gets. */
function outsideMedia(css: string): string {
  let out = ''
  let depth = 0
  for (let i = 0; i < css.length; i++) {
    if (depth === 0 && css.startsWith('@media', i)) {
      depth = -1 // find the opening brace
    }
    const ch = css[i]
    if (depth === -1) { if (ch === '{') depth = 1; continue }
    if (depth > 0) {
      if (ch === '{') depth++
      if (ch === '}') depth--
      continue
    }
    out += ch
  }
  return out
}

it('the 12-column grid and the wide column only exist inside the desktop media query', () => {
  const css = read('./insights.css')
  expect(css).toMatch(/@media \(min-width: 1024px\)/)
  const phone = outsideMedia(css)
  expect(phone).not.toMatch(/repeat\(12/)
  expect(phone).not.toMatch(/shell__main--wide/)
  expect(phone).not.toMatch(/1280px/)
})

it('the bill history two-column layout only exists inside the desktop media query', () => {
  const phone = outsideMedia(read('./bills/bills.css'))
  expect(phone).not.toMatch(/repeat\(2, minmax\(0, 1fr\)\); align-items: start/)
  expect(phone).not.toMatch(/:hover/)
})

// Review findings 8 and 9.
it('every desktop-only table rule sits inside the media query', () => {
  const phone = outsideMedia(read('./insights.css'))
  expect(phone).not.toMatch(/insights__table/)
  expect(phone).not.toMatch(/insights__tablewrap/)
  expect(phone).not.toMatch(/insights__cap/)
  expect(phone).not.toMatch(/insights__year/)
})

it('the desktop bar rule is scoped to the dashboard, not the category screen that shares .insights__bar', () => {
  const css = read('./insights.css')
  const inMedia = css.slice(css.indexOf('@media (min-width: 1024px)'))
  expect(inMedia).not.toMatch(/(^|\n)\s*\.insights__bar\s*[{,]/)
  expect(inMedia).toMatch(/\.insights__bar--wide/)
})

it('the shell lifts its column clamp on <main> for the wide dashboard and the bill history, on desktop only', () => {
  const shell = read('../../shell/shell.css')
  expect(shell).toMatch(/\.shell__main:has\(\.shell__main--wide\)[^}]*max-width: 1280px/)
  expect(outsideMedia(shell)).not.toMatch(/shell__main--wide/)
  const bills = read('./bills/bills.css')
  expect(bills).toMatch(/\.shell__main:has\(\.billhist\)\s*\{\s*max-width: 1100px/)
  expect(outsideMedia(bills)).not.toMatch(/:has\(/)
})

// Integration: a visually hidden span (position: absolute) inside the scrolling table is placed against the page when no
// ancestor is positioned, so its offset in the scrolled table widened the phone's page (scrollWidth 467 at 390).
it('the bill history table scroller is a containing block for the visually hidden labels in it', () => {
  expect(read('./bills/bills.css')).toMatch(/\.billhist__scroll \{[^}]*position: relative/)
})
