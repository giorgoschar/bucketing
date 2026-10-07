import { describe, expect, it } from 'vitest'
import { appRoute } from './appRoute'

describe('appRoute', () => {
  it.each([
    // every link the server creates (scheduler, ingest, login alerts, push test)
    ['/bills', '/app/plan'],
    ['/buckets/3f2a', '/app/plan'],
    ['/buckets', '/app/plan'],
    ['/transactions/abc/edit', '/app/activity'],
    ['/search?q=x', '/app/activity'],
    ['/settings', '/app/settings'],
    ['/settings/2fa/enroll', '/app/settings'],
    ['/stock/shopping', '/app/'],
    ['/stock', '/app/'],
    ['/', '/app/'],
    [null, '/app/'],
    ['', '/app/'],
    ['/billsfoo', '/app/'],
    ['https://elsewhere.example/settings', '/app/settings'], // only the path is used
  ])('%s → %s', (link, expected) => {
    expect(appRoute(link)).toBe(expected)
  })
})
