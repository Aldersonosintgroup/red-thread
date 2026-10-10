import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'

const appVersion = JSON.parse(readFileSync(new URL('./src-tauri/tauri.conf.json', import.meta.url), 'utf-8')).version

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  server: {
    port: 5173,
  },
})
