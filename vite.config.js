import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
    watch: {
      // 这些目录不属于前端源码，避免 Vite 持续扫描模型、向量库和 Python 环境。
      ignored: [
        '**/.venv/**',
        '**/.venv312/**',
        '**/data/**',
        '**/server/**',
        '**/dist/**',
        '**/node_modules/**',
      ],
    },
  },
})
