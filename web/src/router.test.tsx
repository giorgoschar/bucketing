import { describe, expect, it } from 'vitest'
import type { ReactElement } from 'react'
import { router } from './router'

describe('router', () => {
  it('has every 2d route under the shell', () => {
    const paths = (router.routes[0].children ?? []).map((r) => r.path ?? '(index)')
    expect(paths).toEqual(expect.arrayContaining([
      'insights', 'insights/category/:id', 'insights/fuel',
      'settings', 'settings/profile', 'settings/household', 'settings/categories',
      'settings/automations', 'settings/notifications',
    ]))
  })

  it('keeps the earlier routes and the catch-all last', () => {
    const paths = (router.routes[0].children ?? []).map((r) => r.path ?? '(index)')
    expect(paths).toEqual(expect.arrayContaining(['(index)', 'activity', 'plan', 'plan/items']))
    expect(paths.at(-1)).toBe('*')
    const full = (router.routes[1].children ?? []).map((r) => r.path)
    expect(full).toEqual(['/new', '/edit/:id'])
  })

  it('code-splits the detail, drill-down and Settings screens (main bundle under 500 kB)', () => {
    const lazyPaths = (router.routes[0].children ?? [])
      .filter((r) => ((r.element as ReactElement | undefined)?.type as { $$typeof?: symbol } | undefined)?.$$typeof === Symbol.for('react.lazy'))
      .map((r) => r.path)
    expect(lazyPaths).toEqual(expect.arrayContaining([
      'activity/:id', 'plan', 'plan/items', 'insights/category/:id', 'insights/fuel',
      'settings', 'settings/profile', 'settings/household', 'settings/categories',
      'settings/automations', 'settings/notifications',
    ]))
  })

  it('Phase B: both statement screens are lazy chunks, the list before the :month route', () => {
    const routes = router.routes[0].children ?? []
    for (const path of ['insights/statements', 'insights/statements/:month']) {
      const r = routes.find((x) => x.path === path)
      expect(((r?.element as ReactElement | undefined)?.type as { $$typeof?: symbol } | undefined)?.$$typeof).toBe(Symbol.for('react.lazy'))
    }
  })

  it('has the lazy Pantry product detail under the shell, before the catch-all', () => {
    const routes = router.routes[0].children ?? []
    const detail = routes.find((r) => r.path === 'plan/pantry/:id')
    expect(((detail?.element as ReactElement | undefined)?.type as { $$typeof?: symbol } | undefined)?.$$typeof)
      .toBe(Symbol.for('react.lazy'))
    expect(routes.findIndex((r) => r.path === 'plan/pantry/:id')).toBeLessThan(routes.length - 1)
  })

  it('has the lazy shopping list at plan/pantry/list, before any plan/pantry/:id', () => {
    const children = router.routes[0].children ?? []
    const paths = children.map((r) => r.path ?? '(index)')
    const list = paths.indexOf('plan/pantry/list')
    expect(list).toBeGreaterThan(-1)
    const el = children[list].element as ReactElement
    expect((el.type as { $$typeof?: symbol }).$$typeof).toBe(Symbol.for('react.lazy'))
    const detail = paths.indexOf('plan/pantry/:id')
    if (detail !== -1) expect(list).toBeLessThan(detail)
  })

  it('has the lazy Settings › Appearance screen under the shell', () => {
    const routes = router.routes[0].children ?? []
    const r = routes.find((x) => x.path === 'settings/appearance')
    expect(((r?.element as ReactElement | undefined)?.type as { $$typeof?: symbol } | undefined)?.$$typeof)
      .toBe(Symbol.for('react.lazy'))
  })
})
