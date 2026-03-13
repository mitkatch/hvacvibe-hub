import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ws':  { target: 'ws://192.168.1.99:8000', ws: true },
      '/api': { target: 'http://192.168.1.99:8000', changeOrigin: true },
    }
  }
})