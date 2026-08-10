import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const DEV_API_TARGET = globalThis.process?.env?.DEV_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // Povolí prístup z localhostu mimo Docker kontajnera
    port: 5173,
    watch: {
      usePolling: true, // Pomáha hot-reloadingu v Dockeri
    },
    proxy: {
      // Všetky volania backendu idú cez /api na TOM ISTOM origine ako frontend.
      // Vďaka tomu je session cookie first-party a prehliadač ju neblokuje.
      // Bonus: v dev režime tým odpadá aj CORS.
      '/api': {
        target: DEV_API_TARGET,
        changeOrigin: false, // necháme pôvodný Origin, backend ho číta pri set_cookie
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
