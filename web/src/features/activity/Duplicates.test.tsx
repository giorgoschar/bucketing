import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline, TEST_IDENTITY } from '../../test/render'
import { Activity } from './Activity'
import { _resetHeldForTests } from './heldDeletes'
import { TODAY, makeTxn, refRoutes, renderActivity } from './testing'

afterEach(async () => {
  _resetHeldForTests()
  await resetTestEnv()
})

const DISMISS = 'POST /api/v1/transactions/duplicates/dismiss' as const

const a = makeTxn({ id: 'd1', merchant: 'Taverna', amount: 42, created_at: `${TODAY}T20:00:00` })
const b = makeTxn({ id: 'd2', merchant: 'Taverna', amount: 42, created_at: `${TODAY}T20:02:00`, paid_by: 'u-maria' })

function setup(groups = [{ amount: 42, transactions: [a, b] }]) {
  return fakeApi({
    ...refRoutes({ no_payer: 0, duplicate_groups: groups.length }),
    'GET /api/v1/transactions/duplicates': () => ({ groups }) as never,
    [DISMISS]: () => null,
    'DELETE /api/v1/transactions/{txn_id}': () => null,
  })
}

describe('Duplicates mode', () => {
  it('shows pair cards with the gap and disables the other chips', async () => {
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByText('2 min apart')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Income/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Duplicates\? 1/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('Keep both posts the pair', async () => {
    const fake = setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    fireEvent.click(await screen.findByRole('button', { name: 'Keep both' }))
    await waitFor(() => expect(fake.callsTo(DISMISS)[0]?.body).toEqual({ ids: ['d1', 'd2'] }))
  })

  it('tap a row to drop it, then confirm deletes that one (held, with Undo)', async () => {
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    fireEvent.click(await screen.findByRole('button', { name: /Taverna.*Maria/ }))
    expect(screen.getByText('Will be deleted')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete this one' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
    expect(screen.queryByText('2 min apart')).toBeNull() // the pair is resolved
  })

  it('Keep both needs a connection', async () => {
    setOnline(false)
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByRole('button', { name: 'Keep both' })).toBeDisabled()
  })

  it('empty state', async () => {
    setup([])
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByText('No possible duplicates in the last 90 days')).toBeInTheDocument()
  })

  it('a pair whose delete is queued offline is resolved', async () => {
    setIdentity(TEST_IDENTITY)
    await enqueue({ method: 'DELETE', path: '/api/v1/transactions/d2' })
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByText('No possible duplicates in the last 90 days')).toBeInTheDocument()
  })
})
