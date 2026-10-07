import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { writes } from './testHelpers'
import { DEFAULTS, HOUSEHOLD, renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

const press = (...keys: string[]) => keys.forEach((k) => fireEvent.click(screen.getByRole('button', { name: k })))
const openMore = async () => {
  fireEvent.click(screen.getByRole('button', { name: /^More options/ }))
  return screen.findByRole('dialog', { name: 'More' })
}

it('fuel: price per litre prefilled from the last one, litres shown, price sent', async () => {
  const { api } = await renderComposer('/new', {
    defaults: { ...DEFAULTS, last: { ...DEFAULTS.last, category_id: 'c-fuel' }, fuelPrice: '1.600' },
  })
  await screen.findByRole('button', { name: 'Category: Fuel. Change' })
  press('5', '0')
  const more = await openMore()
  expect(within(more).getByLabelText('Price per litre')).toHaveValue('1.600')
  expect(within(more).getByText('Litres: 31.25 L')).toBeInTheDocument()
  fireEvent.click(within(more).getByRole('button', { name: 'Done' }))
  fireEvent.click(screen.getByRole('button', { name: /^Save 50 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ category_id: 'c-fuel', fuel_price_per_litre: '1.600' })
})

it('foreign currency: Save waits for a rate; the ≈ line and the rate are sent', async () => {
  const { api } = await renderComposer()
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Currency: EUR. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'GBP · pounds' }))
  press('2', '0')
  expect(screen.getByRole('button', { name: /^Save 20 pounds/ })).toBeDisabled()
  expect(screen.getByText('Enter the rate')).toBeInTheDocument()
  const more = await openMore()
  expect(within(more).getByText('£20.00 → set a rate')).toBeInTheDocument()
  fireEvent.change(within(more).getByLabelText('Rate'), { target: { value: '1.153' } })
  expect(within(more).getByText('£20.00 → €23.06')).toBeInTheDocument()
  fireEvent.click(within(more).getByRole('button', { name: 'Done' }))
  expect(screen.getByText('≈ €23.06')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Save 20 pounds/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ currency: 'GBP', exchange_rate: '1.153', amount: '20.00' })
})

it('split with Maria: equal shares for every member are sent', async () => {
  const { api } = await renderComposer()
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  press('1', '0')
  const more = await openMore()
  fireEvent.click(within(more).getByRole('switch', { name: 'Split with Maria' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Split' })).getByRole('button', { name: 'Done' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'More' })).getByRole('button', { name: 'Done' }))
  fireEvent.click(screen.getByRole('button', { name: /^Save 10 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({
    payer_mode: 'single', paid_by: 'u1', splits: [{ user_id: 'u1', amount: '5.00' }, { user_id: 'u2', amount: '5.00' }],
  })
})

it('each paid own share: from the payer pill, sent as own_share with no payer', async () => {
  const { api } = await renderComposer()
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  press('1', '0')
  fireEvent.click(screen.getByRole('button', { name: 'Payer: Giorgos. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Each paid own share' }))
  const who = await screen.findByRole('dialog', { name: 'Who paid what' })
  fireEvent.change(within(who).getByLabelText('Giorgos amount'), { target: { value: '7' } })
  fireEvent.change(within(who).getByLabelText('Maria amount'), { target: { value: '3' } })
  fireEvent.click(within(who).getByRole('button', { name: 'Done' }))
  expect(screen.getByRole('button', { name: 'Payer: Each paid own share. Change' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Save 10 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({
    payer_mode: 'own_share', paid_by: null, splits: [{ user_id: 'u1', amount: '7.00' }, { user_id: 'u2', amount: '3.00' }],
  })
})

it('a one-member household has no split row and no own share', async () => {
  await renderComposer('/new', { routes: { 'GET /api/v1/settings/household': { ...HOUSEHOLD, members: [HOUSEHOLD.members[0]] } } })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  const more = await openMore()
  expect(within(more).queryByRole('switch', { name: /^Split with/ })).not.toBeInTheDocument()
})
