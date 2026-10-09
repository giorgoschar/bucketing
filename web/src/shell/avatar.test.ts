// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { avatarInk, avatarLook, contrast } from './avatar'

// The server's AVATAR_COLORS (app/routes/settings.py); Settings › Profile offers the first eight.
const SERVER_COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316', '#f59e0b', '#10b981', '#06b6d4', '#3b82f6', '#84cc16']

describe('avatar initial contrast', () => {
  it('is at least 4.5:1 on every colour a user can pick (the same in both themes)', () => {
    for (const c of SERVER_COLORS) expect(contrast(avatarInk(c), c), c).toBeGreaterThanOrEqual(4.5)
  })

  it('indigo (the default pick) no longer uses the light ink that measured 4.10:1 in dark mode', () => {
    expect(contrast('#F3F5FA', '#6366f1')).toBeLessThan(4.5)
    expect(avatarLook('#6366f1').style).toEqual({ background: '#6366f1', color: avatarInk('#6366f1') })
  })

  it('without a colour it is the token fallback, which meets AA in light and dark', () => {
    expect(avatarLook(null)).toEqual({ className: 'avatar avatar--fallback' })
    expect(avatarLook('red', 'avatar--lg')).toEqual({ className: 'avatar avatar--fallback avatar--lg' })
    const css = readFileSync(new URL('../styles/tokens.css', import.meta.url), 'utf8')
    const blocks = [...css.matchAll(/\{([^{}]*--on-c3:[^{}]*)\}/g)].map(([, b]) => b)
    const themes = [...css.matchAll(/\{([^{}]*--c3:[^{}]*)\}/g)].map(([, b]) => /--c3:\s*(#[0-9A-Fa-f]{6})/.exec(b)![1])
    const ink = /--on-c3:\s*(#[0-9A-Fa-f]{6})/.exec(blocks[0])![1]
    expect(themes.length).toBeGreaterThanOrEqual(3)
    for (const c3 of themes) expect(contrast(ink, c3), `--on-c3 on ${c3}`).toBeGreaterThanOrEqual(4.5)
  })
})
