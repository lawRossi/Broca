const pluginVue = require('eslint-plugin-vue')
const parserTypeScript = require('@typescript-eslint/parser')
const pluginTypeScript = require('@typescript-eslint/eslint-plugin')
const eslintConfigPrettier = require('eslint-config-prettier/flat')
const vueParser = require('vue-eslint-parser')

module.exports = [
  // ============================================================
  // 通用规则（所有 TypeScript/JavaScript 文件）
  // ============================================================
  {
    files: ['src/**/*.{js,ts,tsx}'],
    languageOptions: {
      parser: parserTypeScript,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module'
      }
    },
    plugins: {
      '@typescript-eslint': pluginTypeScript
    },
    rules: {
      ...pluginTypeScript.configs.recommended.rules,
      // 放宽 any 类型 — VS Code API 中有时不可避免
      '@typescript-eslint/no-explicit-any': 'off',
      // VS Code 扩展中 console 用于调试输出是常见的
      'no-console': 'off'
    }
  },

  // ============================================================
  // VS Code 扩展代码（src/extension/）
  // Node.js 环境，CommonJS 模块
  // ============================================================
  {
    files: ['src/extension/**/*.ts'],
    languageOptions: {
      parser: parserTypeScript,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'commonjs',
        project: './tsconfig.extension.json'
      },
      globals: {
        // VS Code API 全局类型
        __dirname: 'readonly',
        __filename: 'readonly',
        require: 'readonly',
        module: 'readonly',
        exports: 'writable',
        process: 'readonly',
        Buffer: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        console: 'readonly'
      }
    },
    rules: {
      // VS Code 扩展不需要浏览器 API
      'no-restricted-globals': 'off',
      // 扩展使用 CommonJS 模块，require() 是标准导入方式
      '@typescript-eslint/no-require-imports': 'off'
    }
  },

  // ============================================================
  // Webview 代码（src/webview/）
  // 浏览器环境，ES Module
  // ============================================================
  {
    files: ['src/webview/src/**/*.{ts,js}'],
    languageOptions: {
      parser: parserTypeScript,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module'
      },
      globals: {
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        fetch: 'readonly',
        URL: 'readonly',
        HTMLElement: 'readonly',
        HTMLDivElement: 'readonly',
        HTMLInputElement: 'readonly',
        HTMLTextAreaElement: 'readonly',
        CustomEvent: 'readonly',
        MouseEvent: 'readonly',
        KeyboardEvent: 'readonly',
        localStorage: 'readonly',
        location: 'readonly',
        Blob: 'readonly',
        File: 'readonly',
        FileReader: 'readonly',
        FormData: 'readonly',
        Headers: 'readonly',
        Request: 'readonly',
        Response: 'readonly',
        DOMException: 'readonly',
        IntersectionObserver: 'readonly',
        ResizeObserver: 'readonly',
        MutationObserver: 'readonly'
      }
    },
    rules: {
      // Node.js 模块在 webview 中不可用
      'no-restricted-modules': ['error', 'fs', 'path', 'os', 'crypto']
    }
  },

  // ============================================================
  // Vue 文件（src/webview/）
  // ============================================================
  ...pluginVue.configs['flat/recommended'].map((config) => ({
    ...config,
    files: ['src/webview/src/**/*.vue']
  })),
  {
    files: ['src/webview/src/**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: '@typescript-eslint/parser',
        ecmaVersion: 'latest',
        sourceType: 'module'
      }
    },
    rules: {
      // 允许单文件组件名称为单个词
      'vue/multi-word-component-names': 'off',
      // 允许 v-html（用于 Markdown 渲染）
      'vue/no-v-html': 'off'
    }
  },

  // ============================================================
  // ⭐ eslint-config-prettier: 禁用所有与 Prettier 冲突的格式规则
  // ============================================================
  eslintConfigPrettier,

  // ============================================================
  // 全局忽略
  // ============================================================
  {
    ignores: ['node_modules/', 'dist/', '*.vsix']
  }
]
