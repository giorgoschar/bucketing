import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
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
})
