// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./items/items.css', import.meta.url), 'utf8')

it('the even form row can shrink, its inputs fill their cell, and it stacks when narrow', () => {
  expect(css).toMatch(/\.items-form__row--even \{ grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\); \}/)
  expect(css).toMatch(/\.items-form__row > \* \{ min-width: 0; \}/)
  expect(css).toMatch(/\.items-form__row :is\(input, select\) \{[^}]*min-width: 0; width: 100%/)
  expect(css).toMatch(/@media \(max-width: 420px\) \{ \.items-form__row--even \{ grid-template-columns: minmax\(0, 1fr\); \} \}/)
})
