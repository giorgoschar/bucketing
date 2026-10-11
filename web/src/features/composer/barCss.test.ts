// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./composer.css', import.meta.url), 'utf8')
const rule = (sel: string) => new RegExp(`${sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? ''

// Fix round 1, finding 5. At 390 px the bar has 358 px: close 44 + gaps 20 + slot. The slot now holds the Offline badge
// (~58) and the Scan button (44 + 4 margin), so a fixed 44 px column made it spill over the Income switch.
it('the header bar sizes its right column to the slot and lets the middle column shrink, so nothing overlaps', () => {
  expect(rule('.composer__bar')).toMatch(/grid-template-columns:\s*44px minmax\(0, 1fr\) auto/)
  expect(rule('.composer__bar .ui-seg')).toMatch(/min-width:\s*0/)
})

it('the Offline badge and the Scan button stay on one line in the slot', () => {
  expect(rule('.composer__slot')).toMatch(/display:\s*flex/)
  expect(rule('.composer__offline')).toMatch(/white-space:\s*nowrap/)
})
