import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Detail } from './Detail'
import { makeTxn, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const PUT = 'PUT /api/v1/transactions/{txn_id}' as const

const ROW = makeTxn({
  id: 'rent', notes: 'Rent', amount: 1100, payer_mode: 'own_share', paid_by: null, category_id: null,
  splits: [{ user_id: 'u-me', amount: 700, is_settled: false }, { user_id: 'u-maria', amount: 400, is_settled: false }],
})

function setup(row = ROW) {
  const fake = fakeApi({
    ...refRoutes(),
    'GET /api/v1/transactions/{txn_id}': () => row,
    'GET /api/v1/transactions/{txn_id}/history': () => ({ events: [] }) as never,
    'GET /api/v1/recurring/entries': () => [],
    [PUT]: (req) => ({ ...row, ...(req.body as object) }),
  })
  renderActivity(<Detail />, { route: `/activity/${row.id}`, path: '/activity/:id' })
  return fake
}

describe('Detail', () => {
  it('a field edit PUTs the full row, keeping splits and payer_mode', async () => {
    const fake = setup()
    fireEvent.click(await screen.findByRole('button', { name: /^Category/ }))
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    await waitFor(() => expect(fake.callsTo(PUT)).toHaveLength(1))
    const put = fake.callsTo(PUT)[0].body as Record<string, unknown>
    expect(put.category_id).toBe('c-groc')
    expect(put.payer_mode).toBe('own_share')
    expect(put.splits).toEqual([{ user_id: 'u-me', amount: 700 }, { user_id: 'u-maria', amount: 400 }])
  })

  it('links the receipt through the API route; Add receipt needs a connection', async () => {
    setup(makeTxn({ id: 'r1', receipt_path: 'x.jpg', merchant: 'Lidl' }))
    expect(await screen.findByRole('link', { name: 'View receipt' })).toHaveAttribute('href', '/api/v1/transactions/r1/receipt')
  })

  it('Add receipt is disabled offline', async () => {
    setOnline(false)
    setup(makeTxn({ id: 'r2', merchant: 'Lidl' }))
    expect(await screen.findByRole('button', { name: /Add receipt/ })).toBeDisabled()
  })

  it('Edit opens the composer route and Copy opens /new?from=', async () => {
    setup()
    expect(await screen.findByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/edit/rent')
    fireEvent.click(screen.getByRole('button', { name: 'Copy as new' }))
    expect(screen.getByTestId('location').textContent).toBe('/new?from=rent')
  })
})
