import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { VitePWA } from 'vite-plugin-pwa'
import { pwaOptions } from './pwa.config.ts'

// The new app is served under /app next to the current Jinja UI until cutover.
// In dev, /api goes to the local FastAPI so requests stay same-origin.
export default defineConfig({
  base: '/app/',
  // Never inline assets as data: URIs; the CSP's font-src is 'self' only.
  build: {
    assetsInlineLimit: 0,
    rollupOptions: {
      output: {
        // react-router (~95 kB) is shared by the entry and most lazy screens. Left to the chunker it lands in
        // whichever chunk the current import graph picks (it flipped into the entry chunk, 323 -> 423 kB).
        // Pinning it keeps the entry chunk small and the split deterministic. check-sw.mjs guards the size.
        manualChunks(id: string) {
          if (/[\\/]node_modules[\\/](react-router|@remix-run[\\/]router)[\\/]/.test(id)) return 'router'
        },
      },
    },
  },
  plugins: [
    react(),
    VitePWA(pwaOptions),
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
