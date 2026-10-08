// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./cash.css', import.meta.url), 'utf8')

it('M1: movement titles wrap (the kit row title is nowrap + ellipsis), so "(deleted)" stays visible at 390 px', () => {
  const block = /\.cash-move \.ui-row__title\s*\{([^}]*)\}/.exec(css)
  expect(block?.[1]).toMatch(/white-space:\s*normal/)
  expect(block?.[1]).toMatch(/overflow-wrap:\s*anywhere/)
})
