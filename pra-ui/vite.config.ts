import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        // Required for SSE (Server-Sent Events) streaming to work through Vite proxy
        headers: {
          'Connection': 'keep-alive',
          'Cache-Control': 'no-cache',
        },
      },
    },
  },
})

