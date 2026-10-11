import { expect, it } from 'vitest'
import { fold as composerFold } from '../composer/defaults'
import cases from './rule_normalisation_cases.json'
import { fold, MAX_PATTERN_LENGTH, normalisePattern } from './normalise'

// The same list the server test reads (tests/fixtures/rule_normalisation_cases.json after integration).
it.each(cases)('$input → $pattern', ({ input, pattern }) => {
  expect(normalisePattern(input)).toBe(pattern)
})

it('the composer matches on the same fold', () => {
  for (const c of cases) expect(composerFold(c.input)).toBe(fold(c.input))
})

it('a very long merchant is cut to the stored length', () => {
  expect(normalisePattern('a'.repeat(300))).toHaveLength(MAX_PATTERN_LENGTH)
})

it('null and undefined are not usable', () => {
  expect(normalisePattern(null)).toBeNull()
  expect(normalisePattern(undefined)).toBeNull()
})

it('text with a mark of unknown combining class is not safe to match on the device', async () => {
  const { isFoldSafe } = await import('./normalise')
  const { matchRule } = await import('../composer/defaults')
  expect(isFoldSafe('Straße ☕️ Αθήνα')).toBe(true)
  expect(isFoldSafe('ก็อปปี้')).toBe(false)
  expect(matchRule('ก็อปปี้ shop', [{ id: 'r', pattern: 'shop', category_id: 'c' }])).toBeNull()
  expect(matchRule('Weißbier Haus', [{ id: 'r', pattern: 'weissbier', category_id: 'c' }])).not.toBeNull()
})
