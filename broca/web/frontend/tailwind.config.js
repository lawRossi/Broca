export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      // 与设计系统一致的色彩
      colors: {
        // 主色调 - 浅蓝色系
        primary: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
        // 中性色 - 灰度系
        gray: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
        },
        // 功能色彩
        success: '#10b981',
        warning: '#f59e0b',
        error: '#ef4444',
        info: '#0ea5e9',
        // 确保primary颜色能正确工作
        'primary-50': '#f0f9ff',
        'primary-100': '#e0f2fe',
        'primary-200': '#bae6fd',
        'primary-300': '#7dd3fc',
        'primary-400': '#38bdf8',
        'primary-500': '#0ea5e9',
        'primary-600': '#0284c7',
        'primary-700': '#0369a1',
        'primary-800': '#075985',
        'primary-900': '#0c4a6e',
      },
      // 字体系统
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
        mono: ['SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'monospace'],
      },
      // 字体大小
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1rem' }],
        sm: ['0.875rem', { lineHeight: '1.25rem' }],
        base: ['1rem', { lineHeight: '1.5rem' }],
        lg: ['1.125rem', { lineHeight: '1.75rem' }],
        xl: ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
        '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
      },
      // 字体粗细
      fontWeight: {
        light: '300',
        normal: '400',
        medium: '500',
        semibold: '600',
        bold: '700',
      },
      // 间距系统 - 4px基准
      spacing: {
        1: '0.25rem', // 4px
        2: '0.5rem', // 8px
        3: '0.75rem', // 12px
        4: '1rem', // 16px
        5: '1.25rem', // 20px
        6: '1.5rem', // 24px
        8: '2rem', // 32px
        10: '2.5rem', // 40px
        12: '3rem', // 48px
        16: '4rem', // 64px
        20: '5rem', // 80px
        24: '6rem', // 96px
      },
      // 圆角系统
      borderRadius: {
        sm: '0.125rem',
        DEFAULT: '0.25rem',
        md: '0.375rem',
        lg: '0.5rem',
        xl: '0.75rem',
        '2xl': '1rem',
        full: '9999px',
      },
      // 阴影系统 - 扁平简约风格
      boxShadow: {
        sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        DEFAULT:
          '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)',
        md: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
        xl: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
        '2xl': '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
        inner: 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.06)',
      },
      // 过渡动画
      transitionDuration: {
        75: '75ms',
        100: '100ms',
        150: '150ms',
        200: '200ms',
        300: '300ms',
        500: '500ms',
        700: '700ms',
        1000: '1000ms',
      },
      transitionTimingFunction: {
        DEFAULT: 'cubic-bezier(0.4, 0, 0.2, 1)',
        'ease-in': 'cubic-bezier(0.4, 0, 1, 1)',
        'ease-out': 'cubic-bezier(0, 0, 0.2, 1)',
        'ease-in-out': 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      // 断点
      screens: {
        xs: '475px',
        sm: '640px',
        md: '768px',
        lg: '1024px',
        xl: '1280px',
        '2xl': '1536px',
      },
      // 容器
      container: {
        center: true,
        padding: {
          DEFAULT: '1rem',
          sm: '2rem',
          lg: '4rem',
          xl: '5rem',
          '2xl': '6rem',
        },
        screens: {
          '2xl': '1400px',
        },
      },
      // Z-index 层级
      zIndex: {
        1: '1',
        10: '10',
        20: '20',
        30: '30',
        40: '40',
        50: '50',
        60: '60',
        70: '70',
        80: '80',
        90: '90',
        100: '100',
      },
      // 最大宽度
      maxWidth: {
        '8xl': '88rem',
        '9xl': '96rem',
      },
      // 最小高度
      minHeight: {
        0: '0',
        '1/4': '25%',
        '1/2': '50%',
        '3/4': '75%',
        full: '100%',
        screen: '100vh',
      },
      // 最小宽度
      minWidth: {
        0: '0',
        '1/4': '25%',
        '1/2': '50%',
        '3/4': '75%',
        full: '100%',
      },
      // 透明度
      opacity: {
        2: '0.02',
        3: '0.03',
        4: '0.04',
        6: '0.06',
        8: '0.08',
        12: '0.12',
        15: '0.15',
        25: '0.25',
        35: '0.35',
        45: '0.45',
        55: '0.55',
        65: '0.65',
        75: '0.75',
        85: '0.85',
        92: '0.92',
        95: '0.95',
        97: '0.97',
        98: '0.98',
      },
    },
  },
  plugins: [
    // 添加自定义样式
    function ({ addUtilities, theme }) {
      const newUtilities = {
        // 渐变文字
        '.text-gradient': {
          background: 'linear-gradient(90deg, #0ea5e9 0%, #3b82f6 100%)',
          '-webkit-background-clip': 'text',
          '-webkit-text-fill-color': 'transparent',
          'background-clip': 'text',
        },
        // 毛玻璃效果
        '.glass': {
          'background-color': 'rgba(255, 255, 255, 0.8)',
          'backdrop-filter': 'blur(10px)',
          border: '1px solid rgba(255, 255, 255, 0.2)',
        },
        // 毛玻璃效果 (暗色)
        '.glass-dark': {
          'background-color': 'rgba(0, 0, 0, 0.8)',
          'backdrop-filter': 'blur(10px)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
        },
        // 安全区域
        '.safe-top': {
          'padding-top': 'env(safe-area-inset-top)',
        },
        '.safe-bottom': {
          'padding-bottom': 'env(safe-area-inset-bottom)',
        },
        '.safe-left': {
          'padding-left': 'env(safe-area-inset-left)',
        },
        '.safe-right': {
          'padding-right': 'env(safe-area-inset-right)',
        },
        // 文本截断
        '.line-clamp-1': {
          overflow: 'hidden',
          display: '-webkit-box',
          '-webkit-box-orient': 'vertical',
          '-webkit-line-clamp': '1',
        },
        '.line-clamp-2': {
          overflow: 'hidden',
          display: '-webkit-box',
          '-webkit-box-orient': 'vertical',
          '-webkit-line-clamp': '2',
        },
        '.line-clamp-3': {
          overflow: 'hidden',
          display: '-webkit-box',
          '-webkit-box-orient': 'vertical',
          '-webkit-line-clamp': '3',
        },
        // 滚动条样式
        '.scrollbar-hide': {
          '-ms-overflow-style': 'none',
          'scrollbar-width': 'none',
          '&::-webkit-scrollbar': {
            display: 'none',
          },
        },
        '.scrollbar-thin': {
          'scrollbar-width': 'thin',
          '&::-webkit-scrollbar': {
            width: '4px',
            height: '4px',
          },
          '&::-webkit-scrollbar-track': {
            background: theme('colors.gray.100'),
          },
          '&::-webkit-scrollbar-thumb': {
            background: theme('colors.gray.300'),
            'border-radius': '2px',
          },
          '&::-webkit-scrollbar-thumb:hover': {
            background: theme('colors.gray.400'),
          },
        },
        // 悬停效果
        '.hover-lift': {
          transition: 'all 0.2s ease-in-out',
          '&:hover': {
            transform: 'translateY(-2px)',
            'box-shadow': theme('boxShadow.md'),
          },
        },
        '.hover-scale': {
          transition: 'all 0.2s ease-in-out',
          '&:hover': {
            transform: 'scale(1.05)',
          },
        },
        '.hover-glow': {
          transition: 'all 0.2s ease-in-out',
          '&:hover': {
            'box-shadow': `0 0 20px ${theme('colors.primary.500')}33`,
          },
        },
        // 聚焦环
        '.focus-ring': {
          '&:focus': {
            outline: 'none',
            'box-shadow': `0 0 0 3px ${theme('colors.primary.500')}33`,
          },
        },
      }

      addUtilities(newUtilities)
    },
    // 暗色模式支持
    function ({ addComponents, theme }) {
      addComponents({
        '.dark-mode': {
          '&': {
            'color-scheme': 'dark',
          },
        },
      })
    },
  ],
  // 暗色模式配置
  darkMode: 'class',

  // 重要前缀
  prefix: '',

  // 重要选择器
  important: false,

  // 变量前缀
  separator: ':',

  // 编译器优化
  safelist: [
    // 动态生成的颜色类
    {
      pattern:
        /bg-(primary|success|warning|error|info)-(50|100|200|300|400|500|600|700|800|900)/,
    },
    {
      pattern:
        /text-(primary|success|warning|error|info)-(50|100|200|300|400|500|600|700|800|900)/,
    },
    {
      pattern:
        /border-(primary|success|warning|error|info)-(50|100|200|300|400|500|600|700|800|900)/,
    },
  ],
}
