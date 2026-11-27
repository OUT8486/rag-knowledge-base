import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const entry = (path) => fileURLToPath(new URL(path, import.meta.url))
export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    rolldownOptions: {
      input: {
        workspace: entry('./index.html'),
        customer: entry('./support/index.html'),
      },
    },
  },
})
