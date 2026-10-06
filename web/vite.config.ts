import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The new app is served under /app next to the current Jinja UI until cutover.
// In dev, /api goes to the local FastAPI so requests stay same-origin.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
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
