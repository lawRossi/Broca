import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
    // 将 MSW 相关文件加入不做转换列表
    deps: {
      inline: ['msw'],
    },
  },
})
