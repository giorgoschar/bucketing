import { describe, expect, it } from 'vitest'
import { appRoute } from './appRoute'
import { routerPathFromSwMessage } from './swMessages'

describe('appRoute: bill-change notifications', () => {
  it('opens the bill history in the app, through the service-worker message', () => {
    expect(appRoute('/app/insights/bills/abc')).toBe('/app/insights/bills/abc')
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/app/insights/bills/abc') })).toBe('/insights/bills/abc')
  })
  it('opens the Bills list from its own path', () => {
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/app/insights/bills') })).toBe('/insights/bills')
  })
  it('works with a full URL and drops a query', () => {
    expect(appRoute('https://tameio.example/app/insights/bills/abc?x=1')).toBe('/app/insights/bills/abc')
  })
  it('does not let a path trick leave the bills screens', () => {
    expect(appRoute('/app/insights/bills/../../settings')).toBe('/app/')
    expect(appRoute('/app/insights/billsfoo')).toBe('/app/')
  })
  it('old bill_drift links to /bills still open Plan', () => {
    expect(appRoute('/bills')).toBe('/app/plan')
    expect(appRoute('/bills/42')).toBe('/app/plan')
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/bills') })).toBe('/plan')
  })
})
