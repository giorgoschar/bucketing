// Pins the Phase 1 PWA settings that moved into pwa.config.ts when 2d switched to injectManifest.
import { describe, expect, it } from 'vitest'
import { pwaOptions } from './pwa.config.ts'

describe('PWA options', () => {
  it('keeps the /app/ scope and the worker at /app/sw.js', () => {
    expect(pwaOptions.scope).toBe('/app/')
    expect(pwaOptions.base).toBe('/app/')
    expect(pwaOptions.manifest).toMatchObject({ id: '/app/', start_url: '/app/', scope: '/app/', display: 'standalone' })
    expect(pwaOptions.srcDir).toBe('src')
    expect(pwaOptions.filename).toBe('sw.ts') // emitted as sw.js
  })

  it('keeps prompt updates, registered by src/pwa/update.ts', () => {
    expect(pwaOptions.registerType).toBe('prompt')
    expect(pwaOptions.injectRegister).toBe(false)
  })

  it('uses our own worker: no generated workbox config, so no runtime caching can be added there', () => {
    expect(pwaOptions.strategies).toBe('injectManifest')
    expect(pwaOptions).not.toHaveProperty('workbox')
  })

  it('precaches the same files as Phase 1 and never the worker itself', () => {
    expect(pwaOptions.injectManifest?.globPatterns).toEqual(['**/*.{js,css,html,woff2,svg,png}'])
    expect(pwaOptions.injectManifest?.globIgnores).toEqual(['**/*-cyrillic*.woff2', '**/*-vietnamese*.woff2', '**/sw.js'])
  })
})
