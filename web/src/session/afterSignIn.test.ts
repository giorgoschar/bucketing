import { afterEach, expect, it } from 'vitest'
import { rememberInvite, takeAfterSignIn } from './afterSignIn'

afterEach(() => sessionStorage.clear())

it('remembers only an invite path, once', () => {
  rememberInvite('/join/abc-123')
  expect(takeAfterSignIn()).toBe('/join/abc-123')
  expect(takeAfterSignIn()).toBeNull()
})

it('ignores anything that is not /join/<token>', () => {
  for (const p of ['/settings', '//evil.example', '/join/', '/join/a/b', 'https://evil.example/join/x']) rememberInvite(p)
  expect(takeAfterSignIn()).toBeNull()
})
