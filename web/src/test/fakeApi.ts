import { vi } from 'vitest'
import type { paths } from '../api/schema'

type Lower = 'get' | 'post' | 'put' | 'patch' | 'delete'
type Op<P extends keyof paths, M extends Lower> = paths[P][M]
type JsonOf<R> = R extends { content: { 'application/json': infer J } } ? J : null
type Success<O> = O extends { responses: infer R }
  ? 200 extends keyof R
    ? JsonOf<R[200 & keyof R]>
    : 201 extends keyof R
      ? JsonOf<R[201 & keyof R]>
      : null
  : never

/** Every "METHOD /path" the schema declares, e.g. "POST /api/v1/recurring/entries/{entry_id}/done". */
type SchemaRoute = {
  [P in keyof paths & string]: {
    [M in Lower]: [Op<P, M>] extends [undefined] ? never : `${Uppercase<M>} ${P}`
  }[Lower]
}[keyof paths & string]
export type Route = SchemaRoute

type PathOf<R> = R extends `${string} ${infer P}` ? P : never
type MethodOf<R> = R extends `${infer M} ${string}` ? Lowercase<M> : never
/** The success body the schema declares for a route (null for a 204). */
export type Reply<R extends Route> = Success<Op<PathOf<R> & keyof paths, MethodOf<R> & Lower>>

export interface FakeRequest {
  method: string
  path: string
  params: Record<string, string>
  query: URLSearchParams
  body: unknown
  headers: Headers
}
export type Handler<R extends Route> = (req: FakeRequest) => Reply<R> | Response | Promise<Reply<R> | Response>
export type Routes = { [R in Route]?: Handler<R> }
export type FakeCall = Omit<FakeRequest, 'params'>

export interface FakeApi {
  calls: FakeCall[]
  /** Calls that matched one route template. */
  callsTo(route: Route): FakeCall[]
  /** Add or replace a handler mid-test. */
  on<R extends Route>(route: R, handler: Handler<R>): void
  /** From now on every request rejects with TypeError('Failed to fetch'), like no connection. */
  down(): void
  up(): void
}

/** An error (or any explicit) response for a handler to return. */
export const reply = (status: number, body?: unknown): Response =>
  body === undefined ? new Response(null, { status }) : Response.json(body, { status })

/** A request that never answers: for "still loading" states. */
export const hang = (): Promise<never> => new Promise<never>(() => {})

function compile(route: string) {
  const [method, pattern] = route.split(' ')
  const names: string[] = []
  const source = pattern.replace(/\{(\w+)\}/g, (_m, name: string) => {
    names.push(name)
    return '([^/]+)'
  })
  return { method, re: new RegExp(`^${source}$`), names, literal: names.length === 0 }
}

/**
 * Replaces globalThis.fetch for the test (restored by vi.restoreAllMocks / resetTestEnv).
 * Works for both the openapi-fetch client (Request objects) and the offline queue (string URLs).
 */
export function fakeApi(routes: Routes = {}): FakeApi {
  const table = new Map<string, (req: FakeRequest) => unknown>()
  for (const [route, handler] of Object.entries(routes)) table.set(route, handler as (req: FakeRequest) => unknown)
  const calls: FakeCall[] = []
  let offline = false

  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    // A FormData body (receipt upload) stays a FormData: jsdom's FormData cannot go through a Node Request.
    const raw = input instanceof Request ? undefined : init?.body
    const multipart = raw instanceof FormData
    const req = input instanceof Request
      ? input
      : new Request(new URL(String(input), globalThis.location.origin), multipart ? { ...init, body: undefined } : init)
    const url = new URL(req.url)
    const text = multipart || req.method === 'GET' || req.method === 'HEAD' ? '' : await req.clone().text()
    const call: FakeCall = {
      method: req.method,
      path: url.pathname,
      query: url.searchParams,
      body: multipart ? raw : text ? (JSON.parse(text) as unknown) : undefined,
      headers: req.headers,
    }
    calls.push(call)
    if (offline) throw new TypeError('Failed to fetch')
    // Literal routes first, so /recurring/entries never lands on /recurring/{item_id}.
    const ordered = [...table.entries()]
      .map(([key, handler]) => ({ ...compile(key), handler }))
      .sort((a, b) => Number(b.literal) - Number(a.literal))
    for (const r of ordered) {
      if (r.method !== req.method) continue
      const m = r.re.exec(url.pathname)
      if (!m) continue
      const params = Object.fromEntries(r.names.map((n, i) => [n, decodeURIComponent(m[i + 1])]))
      const out = await r.handler({ ...call, params })
      if (out instanceof Response) return out
      return out === null || out === undefined ? new Response(null, { status: 204 }) : Response.json(out)
    }
    return reply(404, { detail: `fakeApi: no route for ${req.method} ${url.pathname}` })
  })

  return {
    calls,
    callsTo: (route) => {
      const c = compile(route)
      return calls.filter((x) => x.method === c.method && c.re.test(x.path))
    },
    on: (route, handler) => { table.set(route, handler as (req: FakeRequest) => unknown) },
    down: () => { offline = true },
    up: () => { offline = false },
  }
}
