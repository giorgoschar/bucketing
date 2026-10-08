// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./prompt.css', import.meta.url), 'utf8')
const tsx = readFileSync(new URL('./TickedPrompt.tsx', import.meta.url), 'utf8')

// Playwright pass (390×844): the composer's "Saved €12.00 … Undo" toast lands on the post-save prompt sheet and
// hides "Add them to the pantry?". While the prompt is open, toasts move to the top of the screen.
it('while the post-save prompt is open, toasts sit at the top, clear of the sheet', () => {
  expect(tsx).toContain('className="shop-prompt__acts"')
  const rule = /body:has\(\.shop-prompt__acts\) \.ui-toast-region\s*\{([^}]*)\}/.exec(css)?.[1]
  expect(rule).toMatch(/top:\s*calc\(env\(safe-area-inset-top/)
  expect(rule).toMatch(/bottom:\s*auto/)
})
