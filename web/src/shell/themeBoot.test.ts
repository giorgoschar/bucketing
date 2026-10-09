/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../test/storage'
import { THEME_COLORS, THEME_KEY } from './theme'

// Review I-1: bootTheme() in main.tsx runs only after the deferred module graph has loaded, so a pinned theme
// opposite to the phone's flashed the wrong background on launch. public/theme-boot.js is a classic,
// render-blocking script in <head> that does the same before the first paint. It is a plain file (no
// import), so these tests also pin that its constants match shell/theme.ts.
const web = process.cwd() // vitest's root: web/
const boot = readFileSync(resolve(web, 'public/theme-boot.js'), 'utf8')
const indexHtml = readFileSync(resolve(web, 'index.html'), 'utf8')
const run = () => new Function(boot)()

installMemoryStorage()

const html = () => document.documentElement
const metas = () => [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')].map((m) => m.content)

beforeEach(() => {
  document.head.innerHTML =
    `<meta name="theme-color" media="(prefers-color-scheme: light)" content="${THEME_COLORS.light}">` +
    `<meta name="theme-color" media="(prefers-color-scheme: dark)" content="${THEME_COLORS.dark}">`
  html().removeAttribute('data-theme')
})
afterEach(() => {
  html().removeAttribute('data-theme')
  document.head.innerHTML = ''
})

describe('public/theme-boot.js', () => {
  it('Dark sets data-theme and both status bar colours', () => {
    localStorage.setItem(THEME_KEY, 'dark')
    run()
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(metas()).toEqual([THEME_COLORS.dark, THEME_COLORS.dark])
  })

  it('Light sets data-theme and both status bar colours', () => {
    localStorage.setItem(THEME_KEY, 'light')
    run()
    expect(html().getAttribute('data-theme')).toBe('light')
    expect(metas()).toEqual([THEME_COLORS.light, THEME_COLORS.light])
  })

  it('System (nothing saved, or an unknown value) removes the attribute and leaves the metas alone', () => {
    html().setAttribute('data-theme', 'dark')
    run()
    expect(html().hasAttribute('data-theme')).toBe(false)
    expect(metas()).toEqual([THEME_COLORS.light, THEME_COLORS.dark])
    localStorage.setItem(THEME_KEY, 'sepia')
    run()
    expect(html().hasAttribute('data-theme')).toBe(false)
  })

  it('storage that throws is System, and the script never throws', () => {
    const boom = () => { throw new DOMException('denied', 'SecurityError') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
    expect(run).not.toThrow()
    expect(html().hasAttribute('data-theme')).toBe(false)
  })

  it('is a classic script: no import or export, nothing left on the global object', () => {
    expect(boot).not.toMatch(/^\s*(import|export)\s/m)
    const before = Object.keys(globalThis).length
    run()
    expect(Object.keys(globalThis).length).toBe(before)
  })

  it('uses the same key and colours as shell/theme.ts', () => {
    expect(boot).toContain(`'${THEME_KEY}'`)
    expect(boot).toContain(`light: '${THEME_COLORS.light}'`)
    expect(boot).toContain(`dark: '${THEME_COLORS.dark}'`)
  })
})

describe('index.html loads the theme boot before anything can paint', () => {
  const head = /<head>([\s\S]*)<\/head>/.exec(indexHtml)![1]
  const tag = /<script\b[^>]*theme-boot\.js[^>]*>/.exec(indexHtml)?.[0] ?? ''

  it('a same-origin classic script in <head>: no module, async, defer or inline code (CSP script-src self)', () => {
    expect(head).toContain(tag)
    expect(tag).toBe('<script src="/app/theme-boot.js">')
    expect(indexHtml).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/) // no inline script anywhere
  })

  it('after the theme-color metas it updates, and before the module script and any stylesheet', () => {
    const at = indexHtml.indexOf(tag)
    expect(at).toBeGreaterThan(indexHtml.lastIndexOf('name="theme-color"'))
    expect(at).toBeLessThan(indexHtml.indexOf('type="module"'))
    const sheet = indexHtml.indexOf('rel="stylesheet"')
    if (sheet !== -1) expect(at).toBeLessThan(sheet)
  })
})
