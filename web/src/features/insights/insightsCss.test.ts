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
  const card = /\.insights\.shell__main--wide > :not\(:empty\)\s*\{([^}]*)\}/.exec(desktop)?.[1]
  expect(card).toMatch(/break-inside:\s*avoid/)
  expect(card).toMatch(/display:\s*inline-block/)
  expect(card).toMatch(/vertical-align:\s*top/)
  expect(desktop).toMatch(/\[data-widget='billsPanel'\][^{]*\{\s*display:\s*block;[^}]*column-span:\s*all/s)
  expect(desktop).not.toMatch(/grid-column/)
})
