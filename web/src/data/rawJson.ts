import { readCsrf } from '../api/client'

/** The openapi-fetch result shape, also produced by fetchJson. */
export interface RawResult<T> { data?: T; error?: unknown; response: Response }

/** Same-origin JSON for routes outside the generated types (the cookie /push/* routes). The cookie
 *  routes answer an expired session with a redirect to /login; `manual` turns that into a 401. */
export async function fetchJson<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<RawResult<T>> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-CSRF-Token'] = readCsrf()
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await globalThis.fetch(new URL(path, globalThis.location.origin), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    redirect: 'manual',
  })
  const response = res.type === 'opaqueredirect' ? new Response(null, { status: 401 }) : res
  const text = response.status === 204 ? '' : await response.text()
  let json: unknown
  try {
    json = text ? JSON.parse(text) : undefined
  } catch {
    json = undefined
  }
  return response.ok ? { data: json as T, response } : { error: json, response }
}
