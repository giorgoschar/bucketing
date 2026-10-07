import { afterEach, expect, it } from 'vitest'
import { api } from '../api/client'
import { fakeApi, reply } from '../test/fakeApi'
import { resetTestEnv } from '../test/render'
import { ApiError, detailOf, unwrap } from './http'

afterEach(resetTestEnv)

it('unwrap returns the data on 2xx', async () => {
  fakeApi({ 'GET /api/v1/plan/year': () => ({ months: [], infrequent_monthly_average: 0, estimated: false }) })
  await expect(unwrap(api.GET('/api/v1/plan/year'))).resolves.toEqual({ months: [], infrequent_monthly_average: 0, estimated: false })
})

it('unwrap throws ApiError with the server detail otherwise', async () => {
  fakeApi({ 'GET /api/v1/plan/month': () => reply(400, { detail: 'month must be YYYY-MM.' }) })
  const err = await unwrap(api.GET('/api/v1/plan/month', { params: { query: { month: 'x' } } })).catch((e: unknown) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect(err).toMatchObject({ status: 400, detail: 'month must be YYYY-MM.' })
})

it('detailOf reads strings, turns 422 lists into a readable message and falls back by status', () => {
  expect(detailOf({ detail: 'Already paid.' }, 409)).toBe('Already paid.')
  expect(detailOf({ detail: [{ loc: ['body', 'amount'], msg: 'Field required', type: 'missing' }] }, 422))
    .toBe('Some values aren’t valid. Check them and try again.')
  expect(detailOf(undefined, 401)).toBe('Your session has ended. Sign in again.')
  expect(detailOf('<html>', 418)).toBe('Something went wrong (HTTP 418). Try again.')
})
