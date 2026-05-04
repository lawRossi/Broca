import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

/**
 * Vite plugin to remove 'crossorigin' from script/link tags.
 * VSCode WebView doesn't support CORS, so crossorigin causes script loading failures.
 */
function removeCrossoriginPlugin(): import('vite').Plugin {
  let outDir: string
  return {
    name: 'remove-crossorigin',
    configResolved(config) {
      outDir = config.build.outDir
    },
    closeBundle() {
      // Remove crossorigin from HTML files after build
      const fs = require('fs')
      const path = require('path')
      const htmlDir = resolve(outDir)
      if (!fs.existsSync(htmlDir)) return
      for (const file of fs.readdirSync(htmlDir)) {
        if (!file.endsWith('.html')) continue
        const filePath = path.join(htmlDir, file)
        let html = fs.readFileSync(filePath, 'utf-8')
        html = html.replace(/ crossorigin/g, '')
        fs.writeFileSync(filePath, html)
      }
    }
  }
}

export default defineConfig({
  plugins: [vue(), removeCrossoriginPlugin()],
  root: resolve(__dirname, 'src/webview'),
  base: '',
  build: {
    outDir: resolve(__dirname, 'dist/webview'),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'src/webview/index.html'),
        config: resolve(__dirname, 'src/webview/config.html'),
      },
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src/webview/src'),
    },
  },
})
