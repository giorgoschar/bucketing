import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { VitePWA } from 'vite-plugin-pwa'

// The new app is served under /app next to the current Jinja UI until cutover.
// In dev, /api goes to the local FastAPI so requests stay same-origin.
export default defineConfig({
  base: '/app/',
  // Never inline assets as data: URIs; the CSP's font-src is 'self' only.
  build: { assetsInlineLimit: 0 },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // A separate registerSW.js (not inline) keeps the strict CSP intact.
      injectRegister: 'script',
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
      workbox: {
        navigateFallback: '/app/index.html',
        // Server routes (passkey redirects) and the API must never be answered with the shell.
        navigateFallbackDenylist: [/^\/app\/auth\//, /^\/api\//],
        globPatterns: ['**/*.{js,css,html,woff2,svg,png}'],
        // API data is cached by our encrypted Dexie store, never by the service worker.
        runtimeCaching: [],
      },
    }),
  ],
  test: { environment: 'jsdom', setupFiles: ['src/test/setup.ts'] },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      // The old UI (sign in there, then reload /app) and the passkey sign-in/logout endpoints.
      '/app/auth': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/login': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/static': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/dashboard': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
