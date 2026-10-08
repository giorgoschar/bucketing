import { expect, it } from 'vitest'
import { toBuckets, toCategories } from './reads'

it('buckets keep the date range and the income flag the composer needs', () => {
  const [crete] = toBuckets([
    { id: 'b1', name: 'Crete', kind: 'event', status: 'active', budget: null, start_date: '2026-08-12', end_date: '2026-08-19', show_income: true },
  ])
  expect(crete).toMatchObject({ start_date: '2026-08-12', end_date: '2026-08-19', show_income: true })
  expect(toBuckets([{ id: 'b2', name: 'Day to day' }])[0]).toMatchObject({ start_date: null, end_date: null, show_income: false })
})

it('categories keep system_key (the Fuel category asks for litres)', () => {
  expect(toCategories([{ id: 'c1', name: 'Fuel', system_key: 'fuel' }, { id: 'c2', name: 'Coffee' }]).map((c) => c.system_key)).toEqual(['fuel', null])
})
