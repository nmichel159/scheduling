import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // Povolí prístup z localhostu mimo Docker kontajnera
    port: 5173,
    watch: {
      usePolling: true, // Pomáha hot-reloadingu v Dockeri
    }
  }
})