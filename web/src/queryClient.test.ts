import { expect, it } from 'vitest'
import { ApiError, isRetryable } from './data/http'
import { queryClient } from './queryClient'

it('isRetryable: network errors, 5xx, 408 and 429 are; 4xx (401 above all) are not', () => {
  expect(isRetryable(new TypeError('Failed to fetch'))).toBe(true)
  expect(isRetryable(new ApiError(503, 'down'))).toBe(true)
  expect(isRetryable(new ApiError(500, 'x'))).toBe(true)
  expect(isRetryable(new ApiError(408, 'x'))).toBe(true)
  expect(isRetryable(new ApiError(429, 'x'))).toBe(true)
  expect(isRetryable(new ApiError(401, 'x'))).toBe(false)
  expect(isRetryable(new ApiError(404, 'x'))).toBe(false)
  expect(isRetryable(new ApiError(422, 'x'))).toBe(false)
  expect(isRetryable(new DOMException('aborted', 'AbortError'))).toBe(false)
})

it('queries retry a retryable failure at most twice, and never a 4xx', () => {
  const retry = queryClient.getDefaultOptions().queries?.retry as (n: number, e: unknown) => boolean
  expect(typeof retry).toBe('function')
  expect(retry(0, new ApiError(503, 'down'))).toBe(true)
  expect(retry(1, new TypeError('Failed to fetch'))).toBe(true)
  expect(retry(2, new ApiError(503, 'down'))).toBe(false)
  expect(retry(0, new ApiError(401, 'Not authenticated'))).toBe(false)
  expect(retry(0, new ApiError(400, 'bad'))).toBe(false)
})
