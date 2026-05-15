const pluginVue = require('eslint-plugin-vue')
const parserTypeScript = require('@typescript-eslint/parser')
const pluginTypeScript = require('@typescript-eslint/eslint-plugin')

module.exports = [
  ...pluginVue.configs['flat/recommended'],
  
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
      '@typescript-eslint/no-explicit-any': 'off'
    }
  },
  
  {
    // Override Vue configuration to properly handle TypeScript in Vue files
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: '@typescript-eslint/parser'
      }
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off'
    }
  },
  {
    ignores: ['node_modules/', 'dist/']
  }
]
