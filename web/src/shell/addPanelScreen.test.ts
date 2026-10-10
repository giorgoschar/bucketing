import { expect, it } from 'vitest'
import { panelAddress, rememberScreen, resetScreen } from './addPanel'

it('forgets the last screen on sign-out, so a /new link for the next account opens over Home', () => {
  rememberScreen('/activity/someones-row', '')
  expect(panelAddress('/new', '')).toBe('/activity/someones-row?add=1')
  resetScreen()
  expect(panelAddress('/new', '')).toBe('/?add=1')
})
