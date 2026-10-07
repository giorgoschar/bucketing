import { afterEach, expect, it } from 'vitest'
import { api } from '../api/client'
import { fakeApi, reply } from './fakeApi'
import { entry } from './fixtures'
import { resetTestEnv } from './render'

afterEach(resetTestEnv)

it('answers typed routes, fills path params and records calls with their JSON bodies', async () => {
  const fake = fakeApi({
    'POST /api/v1/recurring/entries/{entry_id}/done': (req) => entry({ id: req.params.entry_id, status: 'done' }),
  })
  const { data } = await api.POST('/api/v1/recurring/entries/{entry_id}/done', {
    params: { path: { entry_id: 'e7' } },
    body: { amount: '12.00', payment_method: 'card' },
  })
  expect(data).toMatchObject({ id: 'e7', status: 'done' })
  expect(fake.callsTo('POST /api/v1/recurring/entries/{entry_id}/done')).toMatchObject([
    { path: '/api/v1/recurring/entries/e7/done', body: { amount: '12.00', payment_method: 'card' } },
  ])
})

it('literal routes win over templated ones; unknown routes are a 404 naming the request', async () => {
  fakeApi({
    'GET /api/v1/recurring/{item_id}': () => reply(500),
    'GET /api/v1/recurring/entries': () => [],
  })
  const ok = await api.GET('/api/v1/recurring/entries', { params: { query: { from: '2026-09-01', to: '2026-10-06' } } })
  expect(ok.response.status).toBe(200)
  const missing = await api.GET('/api/v1/plan/year')
  expect(missing.response.status).toBe(404)
  expect(missing.error).toEqual({ detail: 'fakeApi: no route for GET /api/v1/plan/year' })
})

it('down() makes every request fail at the network level; null replies are 204', async () => {
  const fake = fakeApi({ 'POST /api/v1/matches/{match_id}/dismiss': () => null })
  const res = await api.POST('/api/v1/matches/{match_id}/dismiss', { params: { path: { match_id: 'm1' } } })
  expect(res.response.status).toBe(204)
  fake.down()
  await expect(api.GET('/api/v1/matches')).rejects.toThrow(TypeError)
  fake.up()
})
