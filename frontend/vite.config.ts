import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api/backend': {
        // SAMEPAGE_BACKEND points the dev server at another portal, e.g. http://127.0.0.1:8080.
        target: process.env.SAMEPAGE_BACKEND || 'http://193.36.236.221:21500',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/backend/, ''),
      },
    },
  },
})
