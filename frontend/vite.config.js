import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // In dev, the API runs separately (uvicorn on :8000); paths are identical in production.
    proxy: { '/api': { target: process.env.API_URL || 'http://localhost:8000', changeOrigin: true } },
  },
})
