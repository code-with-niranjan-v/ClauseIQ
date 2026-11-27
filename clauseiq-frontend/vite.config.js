import process from 'node:process'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The page calls /api on its own origin. In development Vite forwards those
// calls to the backend, so no CORS setup or API address is needed in the code.
export default defineConfig(({ mode }) => {
  const backend = loadEnv(mode, process.cwd(), '').VITE_BACKEND_URL || 'http://localhost:8080'
  const proxy = { '/api': { target: backend, timeout: 600000 } }
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { port: 3000, proxy },
  }
})
