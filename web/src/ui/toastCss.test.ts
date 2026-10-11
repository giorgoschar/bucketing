// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./ui.css', import.meta.url), 'utf8')

it('a multi-action toast wraps: the text takes a full row and the buttons sit under it', () => {
  expect(css).toMatch(/\.ui-toast--multi\s*\{[^}]*flex-wrap:\s*wrap/)
  expect(css).toMatch(/\.ui-toast--multi \.ui-toast__text\s*\{[^}]*flex:\s*1 1 100%/)
})
