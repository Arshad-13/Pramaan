import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { configDefaults, defineConfig } from 'vitest/config'

// Dev: Vite on :5173 proxies /api to FastAPI on :8000 so the browser sees one origin
// (same as production, where FastAPI serves the built app). Cookies and CSRF behave identically.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  // Never inline assets as data: URIs: the production Content-Security-Policy only allows fonts
  // from the app's own origin.
  build: { assetsInlineLimit: 0 },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
