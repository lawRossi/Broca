import { marked } from 'marked'

// 配置 marked 选项（与 ChatMessageItem.vue 保持一致）
marked.setOptions({
  breaks: true,
  gfm: true,
})

/**
 * 渲染 Markdown 内容为 HTML（与 ChatMessageItem.vue 中的 renderMarkdown 一致）
 */
export function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    return marked(content, { async: false }) as string
  } catch (e) {
    console.error('Markdown rendering error:', e)
    return content
  }
}
