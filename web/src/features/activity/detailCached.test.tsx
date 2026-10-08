import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../data/keys'
import { fakeApi } from '../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline, testQueryClient } from '../../test/render'
import { Detail } from './Detail'
import { makeTxn, pageOf, refRoutes } from './testing'

afterEach(resetTestEnv)

// P3 final review M4: offline, a row seen in the feed but never opened said "isn't saved on this phone",
// although the feed's cached page holds it.
it('offline, the detail of a row seen in the feed opens from the cached list page', async () => {
  const row = makeTxn({ id: 'seen', merchant: 'Sklavenitis', amount: 23.4 })
  const client = testQueryClient()
  client.setQueryData(keys.transactions.list({ q: 'skl' }, 1), pageOf([makeTxn({ merchant: 'Other' }), row]))
  fakeApi(refRoutes()).down()
  setOnline(false)
  renderWithProviders(<Routes><Route path="/activity/:id" element={<Detail />} /></Routes>, { route: '/activity/seen', client })
  expect(await screen.findByRole('heading', { name: 'Sklavenitis' })).toBeInTheDocument()
  expect(screen.queryByText('This transaction isn’t saved on this phone.')).toBeNull()
})

it('a row in no cached page still says it isn’t saved on this phone', async () => {
  fakeApi(refRoutes()).down()
  setOnline(false)
  renderWithProviders(<Routes><Route path="/activity/:id" element={<Detail />} /></Routes>, { route: '/activity/nope' })
  expect(await screen.findByText('This transaction isn’t saved on this phone.')).toBeInTheDocument()
})

it('online, a 404 says it is gone; another failure offers Retry', async () => {
  const fake = fakeApi({ ...refRoutes(), 'GET /api/v1/transactions/{txn_id}': () => new Response(null, { status: 404 }) })
  const first = renderWithProviders(<Routes><Route path="/activity/:id" element={<Detail />} /></Routes>, { route: '/activity/x' })
  expect(await screen.findByText('This transaction is gone.')).toBeInTheDocument()
  first.unmount()
  fake.on('GET /api/v1/transactions/{txn_id}', () => new Response(null, { status: 503 }))
  renderWithProviders(<Routes><Route path="/activity/:id" element={<Detail />} /></Routes>, { route: '/activity/x' })
  expect(await screen.findByText('Couldn’t load this transaction.')).toBeInTheDocument()
  fake.on('GET /api/v1/transactions/{txn_id}', () => makeTxn({ id: 'x', merchant: 'Back again' }))
  screen.getByRole('button', { name: 'Retry' }).click()
  expect(await screen.findByRole('heading', { name: 'Back again' })).toBeInTheDocument()
})

// Review I-3: the server's 404 is definite. A stale copy in a cached feed page must not reopen the row.
it('online, a 404 says gone even when a cached feed page still holds the row', async () => {
  const row = makeTxn({ id: 'deleted-elsewhere', merchant: 'Sklavenitis' })
  const client = testQueryClient()
  client.setQueryData(keys.transactions.list({ q: 'skl' }, 1), pageOf([row]))
  fakeApi({ ...refRoutes(), 'GET /api/v1/transactions/{txn_id}': () => new Response(null, { status: 404 }) })
  renderWithProviders(<Routes><Route path="/activity/:id" element={<Detail />} /></Routes>, { route: '/activity/deleted-elsewhere', client })
  expect(await screen.findByText('This transaction is gone.')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Sklavenitis' })).toBeNull()
  expect(screen.queryByRole('link', { name: 'Edit' })).toBeNull()
})
