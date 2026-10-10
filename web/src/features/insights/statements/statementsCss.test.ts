// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./statements.css', import.meta.url), 'utf8')
const at = css.indexOf('@media (min-width: 1024px)')
const phone = css.slice(0, at)
const desktop = css.slice(at)

it('every desktop rule sits inside the one media query, which closes the file', () => {
  expect(at).toBeGreaterThan(0)
  expect(css.match(/@media/g)).toHaveLength(1)
  expect(phone).not.toMatch(/:hover|(?<![-\w])columns:|column-span/)
})

it('sections 3 to 7 flow down two columns with inline-block cells; the wide ones span both', () => {
  expect(/\.insights\.stmtpage\s*\{([^}]*)\}/.exec(desktop)?.[1]).toMatch(/columns:\s*2/)
  const cell = /\.stmtpage > \.stmtcell\s*\{([^}]*)\}/.exec(desktop)?.[1]
  expect(cell).toMatch(/display:\s*inline-block/)
  expect(cell).toMatch(/break-inside:\s*avoid/)
  expect(cell).toMatch(/vertical-align:\s*top/)
  expect(/\.stmtpage > \.stmtcell--wide, \.stmtpage > :not\(\.stmtcell\)\s*\{([^}]*)\}/.exec(desktop)?.[1]).toMatch(/column-span:\s*all/)
  expect(desktop).not.toMatch(/grid-column/)
})

it('the page takes the 1100px width of the bill history', () => {
  expect(desktop).toMatch(/\.shell__main:has\(\.stmtpage\)\s*\{[^}]*max-width:\s*1100px/)
})
