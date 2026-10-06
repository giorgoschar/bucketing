import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The new app is served under /app next to the current Jinja UI until cutover.
// In dev, /api goes to the local FastAPI so requests stay same-origin.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
