import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The UI calls /api/... on its own origin. In development Vite forwards those
// requests to the FastAPI server, so the browser never makes a cross-origin call
// and the API needs no CORS settings. In AWS, CloudFront does the same job (Phase 6).
const apiTarget = process.env.KB_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/main.tsx', 'src/test/**'],
    },
  },
})
