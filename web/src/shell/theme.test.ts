import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../test/storage'
import { THEME_COLORS, THEME_KEY, applyTheme, bootTheme, readTheme, saveTheme } from './theme'

installMemoryStorage()

const html = () => document.documentElement
const metas = () => [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')]

beforeEach(() => {
  // index.html: one theme-color per OS scheme.
  document.head.innerHTML =
    `<meta name="theme-color" media="(prefers-color-scheme: light)" content="${THEME_COLORS.light}">` +
    `<meta name="theme-color" media="(prefers-color-scheme: dark)" content="${THEME_COLORS.dark}">`
  html().removeAttribute('data-theme')
})
afterEach(() => {
  html().removeAttribute('data-theme')
  document.head.innerHTML = ''
})

describe('appearance (theme)', () => {
  it('Light and Dark set data-theme on <html>, and the status bar colour follows', () => {
    applyTheme('dark')
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(metas().map((m) => m.content)).toEqual([THEME_COLORS.dark, THEME_COLORS.dark])
    applyTheme('light')
    expect(html().getAttribute('data-theme')).toBe('light')
    expect(metas().map((m) => m.content)).toEqual([THEME_COLORS.light, THEME_COLORS.light])
  })

  it('System removes the attribute and gives each OS scheme its own colour back', () => {
    applyTheme('dark')
    applyTheme('system')
    expect(html().hasAttribute('data-theme')).toBe(false)
    expect(metas().map((m) => m.content)).toEqual([THEME_COLORS.light, THEME_COLORS.dark])
  })

  it('the choice is per device in localStorage "tameio.theme" and survives a reload', () => {
    saveTheme('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    html().removeAttribute('data-theme') // a reload: a fresh document, then the boot runs before React
    bootTheme()
    expect(html().getAttribute('data-theme')).toBe('dark')
    saveTheme('system')
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
    expect(readTheme()).toBe('system')
  })

  it('an unknown stored value is System', () => {
    localStorage.setItem(THEME_KEY, 'sepia')
    expect(readTheme()).toBe('system')
  })

  it('storage that throws falls back to System, and saving never throws', () => {
    const boom = () => { throw new DOMException('denied', 'SecurityError') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
    expect(readTheme()).toBe('system')
    expect(() => bootTheme()).not.toThrow()
    expect(html().hasAttribute('data-theme')).toBe(false)
    expect(() => saveTheme('dark')).not.toThrow()
  })
})
