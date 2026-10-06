import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式: 前端 5173，API 代理到后端 8000（见 pestdet.server）
// 生产模式: `npm run build` 产出 web/dist，由 FastAPI 直接挂载为同源静态站点
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})