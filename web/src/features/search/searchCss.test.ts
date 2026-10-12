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

// Activity's SearchField owns the bare `.search` class (ui-2c.css): its `.search input` rule would
// override `.search__input` and push the sidebar box past the sidebar's edge.
it('the search box and screen do not carry the bare .search class', () => {
  for (const f of ['SearchBox.tsx', 'SearchScreen.tsx']) expect(css(f)).not.toMatch(/className="search[ "]/)
})
