import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// 自签证书（iPhone 等移动设备要求 HTTPS 才能使用 getUserMedia 麦克风权限）
const certDir = resolve(__dirname, 'certs')
const sslConfig = {
  key: readFileSync(resolve(certDir, 'dev-key.pem')),
  cert: readFileSync(resolve(certDir, 'dev-cert.pem')),
}

export default defineConfig({
  plugins: [
    vue(),
    // viteMockServe({ mockPath: 'src/mock', enable: true })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: Number(process.env.VITE_DEV_PORT) || 5177,
    https: sslConfig,
    allowedHosts: ["app.mynotebook.dpdns.org"],
    headers: {
      'Service-Worker-Allowed': '/',
    },
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:9001',
        changeOrigin: true,
        // WebSocket 代理
        ws: true,
      },
      '/socket.io': {
        // 优先级: VITE_BROCA_SOCKET_SERVER_URL > VITE_BACKEND_URL 同 host + 6666 > 默认
        // SocketIO 嵌入 Web 后端进程（BROCA_SOCKETIO_ENABLED=true），
        // 当未显式设置时从 VITE_BACKEND_URL 推导同 host 的 6666 端口
        target:
          process.env.VITE_BROCA_SOCKET_SERVER_URL ||
          (process.env.VITE_BACKEND_URL
            ? process.env.VITE_BACKEND_URL.replace(/:\d+$/, ':6666')
            : 'http://127.0.0.1:6666'),
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
