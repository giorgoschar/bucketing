// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

it('from 1440 px the shell makes room for the Add panel only when the detail pane is not open', () => {
  const css = readFileSync(new URL('./composer.css', import.meta.url), 'utf8')
  const block = css.slice(css.indexOf('@media (min-width: 1440px)'))
  expect(block).toContain('.shell:has(.addpanel):not(:has(.dact__pane)) { padding-right: 440px; }')
  expect(block).not.toMatch(/\.shell:has\(\.addpanel\)\s*\{/)
})
