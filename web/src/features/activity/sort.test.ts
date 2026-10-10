import { expect, it } from 'vitest'
import { fromSearch, toSearch } from './filters'

const TODAY = new Date(2026, 9, 9)

it('reads a valid ?sort= and ignores an unknown or default one', () => {
  expect(fromSearch(new URLSearchParams('sort=amount_desc'), TODAY).sort).toBe('amount_desc')
  expect(fromSearch(new URLSearchParams('sort=bogus'), TODAY)).not.toHaveProperty('sort')
  expect(fromSearch(new URLSearchParams('sort=date_desc'), TODAY)).not.toHaveProperty('sort')
})

it('writes a non-default sort and keeps parameters it does not own', () => {
  const state = fromSearch(new URLSearchParams('sort=date_asc&q=lidl'), TODAY)
  const out = toSearch(state, new URLSearchParams('add=1&mode=cash&q=old&sort=date_asc'))
  expect(out.get('sort')).toBe('date_asc')
  expect(out.get('q')).toBe('lidl')
  expect(out.get('add')).toBe('1')
  expect(out.get('mode')).toBe('cash')
  expect(toSearch({ filter: {}, dups: false, sort: 'date_desc' }).has('sort')).toBe(false)
})
