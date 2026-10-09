// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// The Insights period picker (ui/Chips) and Activity's quick filters (ui/Chip) once shared the global
// `.chips`/`.chip` class names. Both stylesheets ship in one bundle, so the picker picked up the other kit's
// `margin-block: -6px` and `.chip::before { inset: -6px … }` while keeping its own `padding: 2px 0`: the row
// sat under the top bar (the selected chip's top was cut off) and overflowed vertically by 3 px, so the
// horizontal scroller also scrolled up and down (the wobble).
const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8')
const controls = read('./controls.css')
const kit2c = read('./ui-2c.css')
const insights = read('../features/insights/insights.css')
const chipsTsx = read('./Chips.tsx')

const selectors = (css: string) =>
  new Set([...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]))
const rule = (css: string, sel: string) =>
  new RegExp(`${sel.replace(/[.[\]]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? ''

describe('the Chips picker kit', () => {
  it('does not share a class with the 2c Chip kit', () => {
    const own = [...selectors(controls)].filter((c) => c.startsWith('chip'))
    expect(own.length).toBeGreaterThan(0)
    for (const c of own) expect(selectors(kit2c).has(c), `.${c} is also styled by ui-2c.css`).toBe(false)
    expect(chipsTsx).not.toMatch(/className="chips?"/)
  })

  it('never scrolls vertically and keeps room for the focus ring', () => {
    const row = rule(controls, '.chipset')
    expect(row).toMatch(/overflow-x:\s*auto/)
    expect(row).toMatch(/overflow-y:\s*hidden/)
    expect(row).not.toMatch(/margin(-block)?:\s*-/)
    // outline 2px + offset 2px
    expect(row).toMatch(/padding-block:\s*4px/)
  })

  it('the Insights bar bleeds the row to the screen edges with the 16 px inset kept', () => {
    const bar = rule(insights, '.insights__bar .chipset')
    expect(bar).toMatch(/margin-inline:\s*-16px/)
    expect(bar).toMatch(/padding-inline:\s*16px/)
    expect(bar).toMatch(/scroll-padding-inline:\s*16px/)
    expect(bar).not.toMatch(/margin-block/)
  })
})
