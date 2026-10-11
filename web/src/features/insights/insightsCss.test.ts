// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./insights.css', import.meta.url), 'utf8')

// .ui-num is white-space: nowrap; the card footnotes are sentences ("6 months: In … · Out … · Net …")
// and pushed the page 4 px past a 390 px screen. They must wrap.
it('card footnotes that carry .ui-num still wrap', () => {
  const block = /\.insights__foot\.ui-num\s*\{([^}]*)\}/.exec(css)
  expect(block?.[1]).toMatch(/white-space:\s*normal/)
})

// Desktop dashboard: a 2-row grid left a hole under a short card beside a tall one ("In / Out / Net" next to
// "Where it went"). Cards flow down two balanced columns instead; wide cards span both.
it('the desktop dashboard flows cards down two columns, with wide cards across', () => {
  const desktop = css.slice(css.indexOf('@media (min-width: 1024px)'))
  expect(/\.insights\.shell__main--wide\s*\{([^}]*)\}/.exec(desktop)?.[1]).toMatch(/columns:\s*2/)
  // inline-block cards: with block + break-inside: avoid, Chrome leaves a ~300 px hole before the next wide card
  const card = /\.insights\.shell__main--wide > \.insights__panel > :not\(:empty\)\s*\{([^}]*)\}/.exec(desktop)?.[1]
  expect(card).toMatch(/break-inside:\s*avoid/)
  expect(card).toMatch(/display:\s*inline-block/)
  expect(card).toMatch(/vertical-align:\s*top/)
  expect(desktop).toMatch(/\[data-widget='billsPanel'\][^{]*\{\s*display:\s*block;[^}]*column-span:\s*all/s)
  expect(desktop).not.toMatch(/grid-column/)
})

// Phase C §2.2: on desktop each tab uses the two-column flow; Summary, Bills, Statements and the tables span both.
it('the Summary, Bills, Statements and the two tables span both desktop columns; the others flow', () => {
  const desktop = css.slice(css.indexOf('@media (min-width: 1024px)'))
  for (const id of ['summary', 'billsPanel', 'statements', 'monthsTable', 'categoriesTable']) {
    expect(desktop).toContain(`[data-widget='${id}']`)
  }
  const span = /((?:\.insights\.shell__main--wide > \.insights__panel > \[data-widget='[a-zA-Z]+'\],\s*)+)\.insights\.shell__main--wide > \.insights__panel > :not\(\[data-widget\]\)\s*\{[^}]*column-span:\s*all/.exec(desktop)?.[1] ?? ''
  for (const id of ['byMonth', 'biggest', 'method', 'fuel', 'where', 'budgets', 'vsUsual', 'bills']) {
    expect(span).not.toContain(`[data-widget='${id}']`)
  }
})

it('the tab switch is desktop-sized only inside the desktop media query', () => {
  const phone = css.slice(0, css.indexOf('@media (min-width: 1024px)'))
  expect(phone).toMatch(/\.insights__tabs \.ui-seg__opt[^{]*\{[^}]*min-height:\s*44px/)
})

// Fix round 1: the desktop tab switch is a compact control, not the full-width spanning bar.
it('the desktop tab switch is compact and out-specifies the spanning rule', () => {
  const desktop = css.slice(css.indexOf('@media (min-width: 1024px)'))
  const rule = /\.insights\.shell__main--wide > \.insights__tabs\s*\{([^}]*)\}/.exec(desktop)?.[1] ?? ''
  expect(rule).toMatch(/width:\s*fit-content/)
  expect(rule).toMatch(/column-span:\s*all/)
  expect(desktop.indexOf('.insights.shell__main--wide > .insights__tabs')).toBeGreaterThan(desktop.indexOf(':not([data-widget])'))
})

it('a lone flowing card spans both desktop columns', () => {
  const desktop = css.slice(css.indexOf('@media (min-width: 1024px)'))
  expect(desktop).toMatch(/\.insights__flow:not\(:empty\):not\(:has\(~ \.insights__flow:not\(:empty\)\)\):not\(\.insights__flow:not\(:empty\) ~ \.insights__flow\)[^{]*\{[^}]*column-span:\s*all/)
})

it('the phone tabs are text tabs with an underline, not a second segmented bar', () => {
  const phone = css.slice(0, css.indexOf('@media (min-width: 1024px)'))
  expect(phone).toMatch(/\.insights__tabs \.ui-seg__opt\[aria-selected='true'\][^{]*\{[^}]*border-bottom-color:\s*var\(--accent\)/)
  expect(/\.ui-seg\.insights__tabs\s*\{([^}]*)\}/.exec(phone)?.[1]).toMatch(/background:\s*none/)
})
