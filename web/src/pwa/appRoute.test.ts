import { describe, expect, it } from 'vitest'
import { appRoute } from './appRoute'
import { routerPathFromSwMessage } from './swMessages'

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
    // Plan › Pantry (pantry spec §4.9): stock_low links to /stock/shopping, price_drop to /stock.
    ['/stock/shopping', '/app/plan/pantry/list'],
    ['/stock', '/app/plan?view=pantry'],
    ['/stock/3f2a', '/app/plan?view=pantry'],
    ['/stockfoo', '/app/'],
    ['/', '/app/'],
    [null, '/app/'],
    ['', '/app/'],
    ['/billsfoo', '/app/'],
    ['https://elsewhere.example/settings', '/app/settings'], // only the path is used
  ])('%s → %s', (link, expected) => {
    expect(appRoute(link)).toBe(expected)
  })
})

describe('appRoute pantry targets reach a real route', () => {
  it('price_drop (/stock) opens Plan › Pantry, query string kept through the worker message', () => {
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/stock') })).toBe('/plan?view=pantry')
  })
  it('stock_low (/stock/shopping) opens the shopping list route', () => {
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/stock/shopping') })).toBe('/plan/pantry/list')
  })
})
