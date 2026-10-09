// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./activity.css', import.meta.url), 'utf8')

// .ui-num is white-space: nowrap; the filter total is a sentence and must wrap on a 390 px screen.
it('the filter total line figures carry .ui-num and still wrap, in a secondary colour', () => {
  expect(/\.activity__total \.ui-num\s*\{([^}]*)\}/.exec(css)?.[1]).toMatch(/white-space:\s*normal/)
  expect(/\.activity__total\s*\{([^}]*)\}/.exec(css)?.[1]).toMatch(/color:\s*var\(--muted\)/)
})
