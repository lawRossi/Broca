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
    https: sslConfig,
    allowedHosts: ["app.mynotebook.dpdns.org"],
    headers: {
      'Service-Worker-Allowed': '/',
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
        // WebSocket 代理
        ws: true,
      },
    },
  },
})
