// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

it('desktop CSS: two columns about 60/40, 1100px wide, all inside the 1024px query', () => {
  const css = readFileSync(new URL('./home.css', import.meta.url), 'utf8')
  const desktop = /@media \(min-width: 1024px\)\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  expect(desktop).toMatch(/\.shell__main:has\(\.home\)\s*\{\s*max-width: 1100px/)
  expect(desktop).toMatch(/\.home__cols\s*\{[^}]*grid-template-columns:\s*minmax\(0, 3fr\) minmax\(0, 2fr\)/)
  expect(css.replace(desktop, '')).not.toMatch(/grid-template-columns|1100px/)
})

it('desktop: both column headings sit in the same 44px, centred box so they share a baseline', () => {
  const css = readFileSync(new URL('./home.css', import.meta.url), 'utf8')
  const desktop = /@media \(min-width: 1024px\)\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  expect(desktop).toMatch(/\.home__cols \.ui-sec\s*\{[^}]*min-height: 44px;[^}]*align-items: center/)
})
