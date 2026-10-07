import { describe, expect, it } from 'vitest'
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
})
