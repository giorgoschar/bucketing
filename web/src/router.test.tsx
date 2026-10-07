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
})
