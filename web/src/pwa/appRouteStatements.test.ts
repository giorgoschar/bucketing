import { describe, expect, it } from 'vitest'
import { appRoute } from './appRoute'
import { routerPathFromSwMessage } from './swMessages'

describe('appRoute: month-review notifications', () => {
  it('opens the statement in the app, through the service-worker message', () => {
    expect(appRoute('/app/insights/statements/2026-09')).toBe('/app/insights/statements/2026-09')
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/app/insights/statements/2026-09') })).toBe('/insights/statements/2026-09')
  })
  it('opens the statements list from its own path', () => {
    expect(routerPathFromSwMessage({ type: 'navigate', url: appRoute('/app/insights/statements') })).toBe('/insights/statements')
  })
  it('works with a full URL and drops a query', () => {
    expect(appRoute('https://tameio.example/app/insights/statements/2026-09?x=1')).toBe('/app/insights/statements/2026-09')
  })
  it('does not let a path trick leave the statements screens', () => {
    expect(appRoute('/app/insights/statements/../../settings')).toBe('/app/')
    expect(appRoute('/app/insights/statementsfoo')).toBe('/app/')
  })
})
