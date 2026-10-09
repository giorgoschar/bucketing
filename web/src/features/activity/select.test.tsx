import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline, TEST_IDENTITY } from '../../test/render'
import { Activity } from './Activity'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const rows = [makeTxn({ notes: 'one' }), makeTxn({ notes: 'two' }), makeTxn({ notes: 'three' })]

function setup(route = '/activity') {
  fakeApi({
    ...refRoutes({ no_payer: 3, duplicate_groups: 0 }),
    'GET /api/v1/transactions': () => pageOf(rows, { total: 120 }),
  })
  renderActivity(<Activity />, { route })
}

describe('selection mode', () => {
  it('Select, tick, All (server-side count), untick back to hand-picked', async () => {
    setup()
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByText('120 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByText('two'))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    expect(screen.getByRole('toolbar', { name: 'Bulk actions for 2 selected' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('toolbar', { name: /Bulk actions/ })).toBeNull()
  })

  it('selected rows are options with aria-selected in a multi-select listbox', async () => {
    setup()
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    const list = await screen.findByRole('listbox')
    expect(list).toHaveAttribute('aria-multiselectable', 'true')
    const one = screen.getByRole('option', { name: /one/ })
    expect(one).toHaveAttribute('aria-selected', 'false')
    fireEvent.keyDown(one, { key: ' ' })
    expect(one).toHaveAttribute('aria-selected', 'true')
  })

  it('"Select all N" under the No payer chip selects by filter', async () => {
    setup('/activity?missing_payer=1')
    fireEvent.click(await screen.findByRole('button', { name: 'Select all 120' }))
    expect(screen.getByText('120 selected')).toBeInTheDocument()
  })

  it('the bar is disabled offline', async () => {
    setup()
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    act(() => setOnline(false)) // the rows are already on screen
    expect(screen.getByRole('button', { name: 'Bucket' })).toBeDisabled()
    expect(screen.getByText('Needs a connection')).toBeInTheDocument()
  })

  it('unticking after All keeps only visible, selectable rows (no queued edits)', async () => {
    setIdentity(TEST_IDENTITY)
    await enqueue({ method: 'PUT', path: `/api/v1/transactions/${rows[1].id}`, body: { type: 'expense', amount: '10.00', currency: 'EUR', notes: 'two', transaction_date: rows[1].transaction_date } })
    setup()
    expect(await screen.findByText('Waiting to sync')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    fireEvent.click(screen.getByText('one'))
    // "two" has a queued edit, so it can't be picked: only "three" is left.
    expect(screen.getByText('1 selected')).toBeInTheDocument()
  })

  it('All is disabled with no filter at all (the server refuses an empty filter)', async () => {
    setup('/activity?all=1')
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    expect(await screen.findByRole('button', { name: 'All' })).toBeDisabled()
  })

  it('the BulkBar total is the money out of the picked rows (income is not added in)', async () => {
    const out = makeTxn({ notes: 'bread', amount: 10 })
    const pay = makeTxn({ notes: 'salary', amount: 50, type: 'income', bucket_id: null })
    fakeApi({ ...refRoutes(), 'GET /api/v1/transactions': () => pageOf([out, pay]) })
    renderActivity(<Activity />)
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('bread'))
    fireEvent.click(screen.getByText('salary'))
    const bar = screen.getByRole('toolbar', { name: 'Bulk actions for 2 selected' })
    expect(bar).toHaveTextContent('€10.00')
    expect(bar).not.toHaveTextContent('€60.00')
  })

  it('says why All is off when a filter matches more than 1,000 entries, and All stays off', async () => {
    fakeApi({
      ...refRoutes({ no_payer: 3, duplicate_groups: 0 }),
      'GET /api/v1/transactions': () => pageOf(rows, { total: 1400 }),
    })
    renderActivity(<Activity />, { route: '/activity?missing_payer=1' })
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    expect(await screen.findByText('All works for up to 1,000 entries. Narrow the filter.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All' })).toBeDisabled()
  })

  it('shows no cap note while the matches fit', async () => {
    setup('/activity?missing_payer=1')
    fireEvent.click(await screen.findByRole('button', { name: 'Select all 120' }))
    await screen.findByText('120 selected')
    expect(screen.queryByText(/All works for up to/)).toBeNull()
  })
})
