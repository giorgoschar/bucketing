// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8')
/** The min-height in px of the last rule whose selector list is exactly `selector`. */
function minHeight(css: string, selector: string): number | null {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const blocks = [...css.matchAll(new RegExp(`(?:^|\\})\\s*${esc}\\s*\\{([^}]*)\\}`, 'g'))]
  const hits = blocks.map((b) => /min-height:\s*(\d+)px/.exec(b[1])).filter(Boolean)
  return hits.length ? Number(hits[hits.length - 1]![1]) : null
}

it.each([
  ['../features/composer/composer.css', '.composer__modes .ck-chip'],
  ['../ui/composer-kit.css', '.amount__cur'],
  ['../features/composer/pickers/pickers.css', '.ck-chip'],
  ['../features/composer/pickers/pickers.css', '.ck-date__input'],
  ['../ui/ui.css', '.ui-seg__opt'],
])('%s %s is at least 44px tall (Apple HIG tap target)', (file, selector) => {
  expect(minHeight(read(file), selector)).toBeGreaterThanOrEqual(44)
})
