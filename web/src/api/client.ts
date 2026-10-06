import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const listeners = new Set<() => void>()

export function readCsrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

export function onUnauthorized(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

const session: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method)) request.headers.set('X-CSRF-Token', readCsrf())
    return request
  },
  onResponse({ response }) {
    if (response.status === 401) listeners.forEach((cb) => cb())
    return response
  },
}

// openapi-fetch needs an absolute base (jsdom/Node reject relative Request URLs); the page origin
// keeps calls same-origin. fetch is resolved per call so tests can spy on globalThis.fetch.
export const api = createClient<paths>({
  baseUrl: globalThis.location.origin,
  credentials: 'same-origin',
  fetch: (request) => globalThis.fetch(request),
})
api.use(session)
