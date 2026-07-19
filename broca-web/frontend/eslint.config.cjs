const pluginVue = require('eslint-plugin-vue')
const parserTypeScript = require('@typescript-eslint/parser')
const pluginTypeScript = require('@typescript-eslint/eslint-plugin')
const eslintConfigPrettier = require('eslint-config-prettier/flat')

module.exports = [
  // Vue 官方推荐规则（含代码质量和部分格式规则）
  ...pluginVue.configs['flat/recommended'],

  // TypeScript 规则（仅代码质量/类型检查，格式由 Prettier 负责）
  {
    files: ['**/*.{ts,tsx}'],
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
      // 放宽 any 类型 — 项目中有时不可避免
      '@typescript-eslint/no-explicit-any': 'off'
    }
  },

  // Vue + TypeScript 文件特殊处理
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: '@typescript-eslint/parser'
      }
    },
    rules: {
      // 允许单文件组件名称为单个词（如 Chat.vue）
      'vue/multi-word-component-names': 'off'
    }
  },

  // ⭐ eslint-config-prettier: 禁用所有与 Prettier 冲突的 ESLint 格式规则
  // 必须放在靠后的位置，以确保覆盖前面插件开启的格式规则
  eslintConfigPrettier,

  // 全局忽略
  {
    ignores: ['node_modules/', 'dist/', '.vite-temp/']
  }
]
