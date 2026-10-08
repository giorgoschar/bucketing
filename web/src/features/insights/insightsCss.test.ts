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
