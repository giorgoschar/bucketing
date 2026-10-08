import type { VitePWAOptions } from 'vite-plugin-pwa'

/**
 * The /app/ PWA. 2d moved from generateSW to injectManifest so src/sw.ts can handle push; the Phase 1
 * behaviour is unchanged: scope /app/, worker at /app/sw.js (existing installs update in place),
 * prompt-style updates applied by src/pwa/update.ts at a safe moment, no runtime caching.
 * The navigate fallback and its denylist live in src/sw.ts. Pinned by pwa.config.test.ts,
 * src/sw.test.ts and scripts/check-sw.mjs (run after every build).
 */
export const pwaOptions: Partial<VitePWAOptions> = {
  strategies: 'injectManifest',
  srcDir: 'src',
  filename: 'sw.ts',
  registerType: 'prompt',
  injectRegister: false,
  includeManifestIcons: false,
  scope: '/app/',
  base: '/app/',
  manifest: {
    name: 'Tameio',
    short_name: 'Tameio',
    id: '/app/',
    start_url: '/app/',
    scope: '/app/',
    display: 'standalone',
    background_color: '#090B10',
    theme_color: '#090B10',
    icons: [
      { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
      { src: 'icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  },
  injectManifest: {
    globPatterns: ['**/*.{js,css,html,woff2,svg,png}'],
    // Latin + Greek (merchant names) only; skip the other unicode-range subsets. Never precache the worker.
    globIgnores: ['**/*-cyrillic*.woff2', '**/*-vietnamese*.woff2', '**/sw.js'],
    // One classic script, as the generated worker was (iOS registers it as classic).
    rollupFormat: 'iife',
  },
}
