// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./ui-2c.css', import.meta.url), 'utf8')

it('the swipe Delete label uses --on-neg, not a fixed white (2.75:1 on the dark --neg)', () => {
  const block = /\.swipe__delete\s*\{([^}]*)\}/.exec(css)
  expect(block?.[1]).toMatch(/color:\s*var\(--on-neg\)/)
})
