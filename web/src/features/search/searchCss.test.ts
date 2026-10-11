import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it } from 'vitest'

const css = (f: string) => readFileSync(join(__dirname, f), 'utf8')

it('the desktop-only rules sit inside the 1024 px query', () => {
  const search = css('search.css')
  const outside = search.slice(0, search.indexOf('@media (min-width: 1024px)'))
  expect(outside).not.toMatch(/\.search--box|\.search__panel/)
  const shell = css('../../shell/shell.css')
  const topbarSearchHide = shell.indexOf('.topbar__search { display: none; }')
  expect(topbarSearchHide).toBeGreaterThan(shell.indexOf('@media (min-width: 1024px)'))
  expect(shell.slice(0, shell.indexOf('@media (min-width: 1024px)'))).toMatch(/\.topbar__search \{[^}]*width: 44px; height: 44px/)
})
