import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { settingsOptions, statementOptions } from './localGroups'
import { SETTINGS_PAGES } from './settingsIndex'

const months = [
  { month: '2026-09', label: 'September 2026' },
  { month: '2026-08', label: 'August 2026' },
  { month: '2025-09', label: 'September 2025' },
]

it('statements match on the month name, case and accents aside', () => {
  expect(statementOptions(months, 'SEPT').map((o) => o.label)).toEqual(['September 2026', 'September 2025'])
  expect(statementOptions(months, 'august')[0].to).toBe('/insights/statements/2026-08')
})

it('statements match on YYYY-MM, and need 2 characters', () => {
  expect(statementOptions(months, '2026-09').map((o) => o.to)).toEqual(['/insights/statements/2026-09'])
  expect(statementOptions(months, '2')).toEqual([])
  expect(statementOptions(months, 'zzz')).toEqual([])
})

it('"dark" finds Appearance and "token" finds Automations', () => {
  expect(settingsOptions('dark').map((o) => o.label)).toEqual(['Appearance'])
  expect(settingsOptions('token').map((o) => [o.label, o.to])).toEqual([['Automations', '/settings/automations']])
})

it('every settings page is found by its own name and by each keyword', () => {
  for (const p of SETTINGS_PAGES) {
    expect(settingsOptions(p.title).map((o) => o.to)).toContain(p.to)
    for (const k of p.keywords) if (k.length >= 2) expect(settingsOptions(k).map((o) => o.to)).toContain(p.to)
  }
})

it('the index lists every settings route the router has', () => {
  const router = readFileSync(join(__dirname, '../../router.tsx'), 'utf8')
  const routes = [...router.matchAll(/path: '(settings\/[a-z]+)'/g)].map((m) => `/${m[1]}`)
  expect(routes.length).toBeGreaterThan(0)
  expect(SETTINGS_PAGES.map((p) => p.to).sort()).toEqual(routes.sort())
})

it('% and _ are plain text for the device-side match', () => {
  expect(settingsOptions('%%')).toEqual([])
  expect(statementOptions(months, '_ _')).toEqual([])
})
