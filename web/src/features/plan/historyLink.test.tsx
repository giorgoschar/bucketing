import { screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { entry, item, page, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { EntrySheet } from './EntrySheet'
import { ItemSheet } from './items/ItemSheet'

afterEach(resetTestEnv)

const routes = () => ({ ...readRoutes(), 'GET /api/v1/transactions': () => page([]) })

it('the item sheet links an existing out item to its history', () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={item()} onClose={() => {}} />)
  expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute('href', '/insights/bills/i1')
})

it('a new item has no history link, and neither does an In item', () => {
  fakeApi(routes())
  const { unmount } = renderWithProviders(<ItemSheet open item={null} onClose={() => {}} />)
  expect(screen.queryByRole('link', { name: 'History' })).toBeNull()
  unmount()
  renderWithProviders(<ItemSheet open item={item({ direction: 'in' })} onClose={() => {}} />)
  expect(screen.queryByRole('link', { name: 'History' })).toBeNull()
})

it('the entry sheet links an out entry to its item history, in the menu', () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry()} onClose={() => {}} />)
  expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute('href', '/insights/bills/i1')
})

it('an In entry has no history link', () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ direction: 'in' })} onClose={() => {}} />)
  expect(screen.queryByRole('link', { name: 'History' })).toBeNull()
})
