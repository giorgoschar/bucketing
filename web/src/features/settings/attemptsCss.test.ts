// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./settings.css', import.meta.url), 'utf8')
const rule = (sel: string) => new RegExp(`${sel.replace(/[.]/g, '\\.')}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? ''

// A rejected attempt's reason is why the screen exists: it wraps, and nothing cuts it short.
it('the attempt reason wraps and is never truncated', () => {
  const r = rule('.attempt__reason')
  expect(r).toMatch(/white-space:\s*normal/)
  expect(r).toMatch(/overflow-wrap:\s*anywhere/)
  expect(r).not.toMatch(/text-overflow|line-clamp|overflow:\s*hidden/)
  expect(rule('.attempt')).not.toMatch(/overflow:\s*hidden/)
})

it('the merchant and amount line wraps too, and the tap targets are 44 px', () => {
  expect(rule('.attempt__what')).toMatch(/overflow-wrap:\s*anywhere/)
  expect(rule('.attempt__time')).toMatch(/min-height:\s*44px/)
  expect(rule('.attempt__link')).toMatch(/min-height:\s*44px/)
  expect(rule('.attempt__time.ui-num')).toMatch(/white-space:\s*normal/)
})
