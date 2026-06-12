<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useChatStore, useSocketStore } from '@/stores'
import { renderMarkdown } from '@/utils/markdown'

const chatStore = useChatStore()
const socketStore = useSocketStore()

interface ToolCallStat {
  toolName: string
  count: number
}

interface TodoItem {
  name: string
  status: 'pending' | 'in_progress' | 'completed'
}

interface TurnSummary {
  turnId: string
  sequenceNumber: number
  agentId: string
  agentName: string
  userMessage: string | null
  status: 'active' | 'thinking' | 'calling_tool' | 'completed' | 'error'
  currentTool: string | null
  currentFilePath: string | null
  currentTodoList: TodoItem[]
  totalDuration: number
  totalSteps: number
  toolCallStats: ToolCallStat[]
  finalResponse: string
  reasoningContent: string
  isActive: boolean
  startedAt: number
  createdAt: string
  lastMessageId: string | null
}

const props = defineProps<{
  turn: TurnSummary
  consecutiveAgent: boolean
}>()

// 折叠状态：推理内容
const showReasoning = ref(false)
// 悬停显示操作按钮
const showActions = ref(false)

// ====== 状态简化：只显示 进行中 / 已完成 / 中断 ======

const simplifiedStatus = computed(() => {
  if (props.turn.status === 'completed') return 'completed'
  if (props.turn.status === 'error') return 'error'
  return 'active'  // active / thinking / calling_tool 统一为"进行中"
})

const statusText = computed(() => {
  const map: Record<string, string> = {
    active: '进行中',
    completed: '已完成',
    error: '中断',
  }
  return map[simplifiedStatus.value]
})

const statusBorderClass = computed(() => {
  const map: Record<string, string> = {
    active: 'border-l-blue-400',
    completed: 'border-l-green-500',
    error: 'border-l-red-500',
  }
  return map[simplifiedStatus.value] || 'border-l-gray-400'
})

const headerTextClass = computed(() => {
  if (simplifiedStatus.value === 'completed') return 'text-green-700'
  if (simplifiedStatus.value === 'error') return 'text-red-700'
  return 'text-gray-700'
})

const statusColorClass = computed(() => {
  const map: Record<string, string> = {
    active: 'text-blue-600',
    completed: 'text-green-600',
    error: 'text-red-600',
  }
  return map[simplifiedStatus.value] || 'text-gray-600'
})

const statusDotClass = computed(() => {
  const map: Record<string, string> = {
    active: 'bg-blue-400 animate-pulse',
    completed: 'bg-green-500',
    error: 'bg-red-500',
  }
  return map[simplifiedStatus.value] || 'bg-gray-400'
})

// 格式化耗时
const formattedDuration = computed(() => {
  const seconds = Math.round(props.turn.totalDuration)
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}分${secs}秒`
})

// 格式化完成时刻（对已完成的 turn，用 startedAt + totalDuration 算出结束时间）
const formattedCompletionTime = computed(() => {
  if (props.turn.status !== 'completed') return ''
  const endMs = props.turn.startedAt + props.turn.totalDuration * 1000
  const d = new Date(endMs)
  const now = new Date()
  const pad = (n: number) => n.toString().padStart(2, '0')
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  // 非当天显示完整日期
  if (
    d.getFullYear() !== now.getFullYear() ||
    d.getMonth() !== now.getMonth() ||
    d.getDate() !== now.getDate()
  ) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
  }
  return time
})

// 当前调用工具名
const currentToolText = computed(() => {
  return props.turn.currentTool || ''
})

// 是否显示文件路径
const showFilePath = computed(() => {
  return props.turn.currentFilePath &&
    props.turn.currentTool &&
    ['read_file', 'edit_file', 'write_file'].includes(props.turn.currentTool)
})

// 是否显示 TODO 列表
const showTodoList = computed(() => {
  return props.turn.currentTodoList && props.turn.currentTodoList.length > 0
})

// 是否显示工具统计
const showToolStats = computed(() => {
  return props.turn.toolCallStats && props.turn.toolCallStats.length > 0
})

// 工具统计文本
const toolStatsText = computed(() => {
  return props.turn.toolCallStats
    .map(s => `${s.toolName} (${s.count}次)`)
    .join(', ')
})

// 是否显示回复区域（有 finalResponse 时）
const showResponse = computed(() => {
  return props.turn.finalResponse.length > 0
})

// 是否有推理内容可展开
const hasReasoning = computed(() => {
  return props.turn.reasoningContent.length > 0
})

// ====== 撤销功能 ======

// 是否可撤销
const canUndo = computed(() => {
  return (
    chatStore.connected &&
    chatStore.sessionId &&
    chatStore.runnerAlive &&
    !chatStore.isAgentOrchestration &&
    props.turn.status === 'completed' &&
    props.turn.lastMessageId
  )
})

// 确认撤销
const confirmUndo = () => {
  ElMessageBox.confirm(
    `确定要撤销"第${props.turn.sequenceNumber}轮"操作吗？`,
    '确认撤销',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    }
  )
    .then(() => handleUndo())
    .catch(() => {})
}

// 执行撤销
const handleUndo = async () => {
  if (!canUndo.value || !chatStore.sessionId || !props.turn.lastMessageId) return

  try {
    await socketStore.sendUndo({
      targetMessageId: props.turn.lastMessageId,
      level: 'turn',
      subscription: chatStore.sessionId,
      receiverId: props.turn.agentId,
    })
  } catch (error) {
    console.error('撤销失败:', error)
  }
}
</script>

<template>
  <div
    :class="[
      'rounded-lg p-2 sm:p-3 transition-all duration-200 bg-white',
      statusBorderClass,
      consecutiveAgent ? 'mt-1' : 'mt-3',
    ]"
    style="border-left-width: 4px;"
    @mouseenter="showActions = true"
    @mouseleave="showActions = false"
  >
    <!-- 标题栏 -->
    <div class="flex items-center justify-between gap-2 mb-2">
      <div class="flex items-center gap-2">
        <span :class="['inline-block w-2.5 h-2.5 rounded-full', statusDotClass]"></span>
        <span class="font-semibold text-sm" :class="headerTextClass">{{ turn.agentName }}</span>
        <span class="text-xs text-gray-400">第{{ turn.sequenceNumber }}轮</span>
      </div>
      <div class="flex items-center gap-2 text-xs">
        <span v-if="formattedCompletionTime" class="text-gray-400" :title="'完成于 ' + formattedCompletionTime">🕐 {{ formattedCompletionTime }}</span>
        <span class="text-gray-500 opacity-70">⏱️ {{ formattedDuration }}</span>
      </div>
    </div>

    <!-- 用户消息 -->
    <div v-if="turn.userMessage" class="py-2 border-b border-gray-100">
      <div class="flex items-start gap-2 text-xs sm:text-sm text-gray-600">
        <span class="flex-shrink-0">👤</span>
        <div>{{ turn.userMessage }}</div>
      </div>
    </div>

    <!-- 执行摘要 -->
    <div class="py-2 border-b border-gray-100">
      <div class="flex items-center gap-1 mb-1.5 text-xs text-gray-400">
        <span>📊</span>
        <span class="font-medium">执行摘要</span>
      </div>
      <div class="space-y-1 text-xs">
        <div class="flex items-center gap-2">
          <span class="text-gray-400 w-16 flex-shrink-0">📋 步骤</span>
          <span class="text-gray-700">{{ turn.totalSteps }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-gray-400 w-16 flex-shrink-0">🔄 状态</span>
          <span :class="statusColorClass">{{ statusText }}</span>
        </div>
        <div v-if="currentToolText" class="flex items-center gap-2">
          <span class="text-gray-400 w-16 flex-shrink-0">🔧 工具</span>
          <span class="text-gray-700">{{ currentToolText }}</span>
        </div>
        <div v-if="showFilePath" class="flex items-center gap-2">
          <span class="text-gray-400 w-16 flex-shrink-0">📁 文件</span>
          <span class="text-gray-700 truncate max-w-full" :title="turn.currentFilePath!">{{ turn.currentFilePath }}</span>
        </div>
        <div v-if="showTodoList" class="pt-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-gray-400 w-16 flex-shrink-0">📝 任务</span>
          </div>
          <div class="params-inner p-2 rounded border ml-2">
            <div v-for="(todo, idx) in turn.currentTodoList" :key="idx" class="mb-2 last:mb-0">
              <div class="flex items-start gap-2">
                <span class="mt-1 text-sm">
                  <span v-if="todo.status === 'completed'">✅</span>
                  <span v-else-if="todo.status === 'in_progress'">⏳</span>
                  <span v-else>⬜️</span>
                </span>
                <div class="flex-1">
                  <div class="params-todo-name text-sm font-medium">
                    {{ todo.name }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="showToolStats" class="flex items-start gap-2">
          <span class="text-gray-400 w-16 flex-shrink-0">📈 调用</span>
          <span class="text-gray-600">{{ toolStatsText }}</span>
        </div>
      </div>
    </div>

    <!-- 回复区域 -->
    <div v-if="showResponse" class="pt-2">
      <div class="markdown-content text-gray-800 text-xs sm:text-sm leading-relaxed overflow-x-auto"
        v-html="renderMarkdown(turn.finalResponse)"></div>
    </div>

    <!-- 推理内容（可折叠，放在回复之后，样式与明细模式一致） -->
    <div v-if="hasReasoning" class="pt-2">
      <button
        class="flex items-center gap-1 text-xs !text-amber-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
        @click="showReasoning = !showReasoning"
      >
        <span>{{ showReasoning ? '▼' : '▶' }}</span>
        <span class="text-xs">思考</span>
        <span v-if="!showReasoning && simplifiedStatus === 'active'" class="animate-pulse text-amber-500">...</span>
      </button>
      <div v-if="showReasoning" class="mt-2 p-3 bg-amber-50 rounded-lg border border-amber-200">
        <pre class="text-xs font-mono text-amber-800 whitespace-pre-wrap break-words leading-relaxed">{{ turn.reasoningContent }}</pre>
      </div>
    </div>

    <!-- 悬停撤销按钮（底部右对齐） -->
    <div v-if="showActions && canUndo" class="flex justify-end pt-1">
      <el-button
        size="small"
        link
        @click.stop="confirmUndo"
        title="撤销此轮操作"
        class="!p-1 !min-h-0 !h-auto undo-button"
      >
        <span class="text-xs">↩️ 撤销</span>
      </el-button>
    </div>
  </div>
</template>


<style scoped>
/* ========== Markdown 样式（与 ChatMessageItem 严格一致） ========== */

:deep(.markdown-content) {
  word-wrap: break-word;
  overflow-wrap: break-word;
}

:deep(.markdown-content h1),
:deep(.markdown-content h2),
:deep(.markdown-content h3),
:deep(.markdown-content h4),
:deep(.markdown-content h5),
:deep(.markdown-content h6) {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.25;
}

:deep(.markdown-content h1) {
  font-size: 1.5em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

:deep(.markdown-content h2) {
  font-size: 1.3em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

:deep(.markdown-content h3) {
  font-size: 1.1em;
}

:deep(.markdown-content p) {
  margin-bottom: 1em;
  line-height: 1.6;
}

:deep(.markdown-content ul),
:deep(.markdown-content ol) {
  padding-left: 2em;
  margin-bottom: 1em;
}

:deep(.markdown-content li) {
  margin-bottom: 0.25em;
}

:deep(.markdown-content blockquote) {
  margin: 1em 0;
  padding: 0 1em;
  color: #6a737d;
  border-left: 0.25em solid #dfe2e5;
  background-color: #f6f8fa;
  padding: 0.5em 1em;
  border-radius: 0 4px 4px 0;
}

:deep(.markdown-content code) {
  font-family:
    ui-monospace,
    SFMono-Regular,
    SF Mono,
    Menlo,
    Consolas,
    Liberation Mono,
    monospace;
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}

:deep(.markdown-content pre) {
  background-color: #f6f8fa;
  border-radius: 6px;
  padding: 1em;
  overflow: auto;
  margin: 1em 0;
}

:deep(.markdown-content pre code) {
  background-color: transparent;
  padding: 0;
  font-size: 0.8em;
  line-height: 1.45;
}

:deep(.markdown-content table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
}

:deep(.markdown-content table th),
:deep(.markdown-content table td) {
  border: 1px solid #dfe2e5;
  padding: 0.6em 1em;
}

:deep(.markdown-content table th) {
  font-weight: 600;
  background-color: #f6f8fa;
}

:deep(.markdown-content tr:nth-child(2n)) {
  background-color: #f6f8fa;
}

:deep(.markdown-content a) {
  color: #0366d6;
  text-decoration: none;
}

:deep(.markdown-content a:hover) {
  text-decoration: underline;
}

:deep(.markdown-content img) {
  max-width: 100%;
  height: auto;
}

:deep(.markdown-content hr) {
  height: 0.25em;
  padding: 0;
  margin: 1.5em 0;
  background-color: #e1e4e8;
  border: 0;
}

:deep(.markdown-content strong) {
  font-weight: 600;
}

:deep(.markdown-content em) {
  font-style: italic;
}

:deep(.markdown-content del) {
  text-decoration: line-through;
}

/* ========== 暗色模式（与 ChatMessageItem 严格一致） ========== */
@media (prefers-color-scheme: dark) {
  /* --- Markdown（与 ChatMessageItem 完全一致） --- */
  :deep(.markdown-content h1),
  :deep(.markdown-content h2),
  :deep(.markdown-content h3),
  :deep(.markdown-content h4),
  :deep(.markdown-content h5),
  :deep(.markdown-content h6) {
    color: #0f172a;
    border-bottom-color: #cbd5e1;
  }

  :deep(.markdown-content blockquote) {
    color: #334155;
    border-left-color: #64748b;
    background-color: #e2e8f0;
  }

  :deep(.markdown-content table th) {
    background-color: #cbd5e1;
    font-weight: 700;
    color: #0f172a;
  }

  :deep(.markdown-content a) {
    color: #1d4ed8;
  }

  /* --- 卡片分隔线 --- */
  .border-gray-100 {
    border-color: #334155;
  }
  .border-b-gray-100 {
    border-bottom-color: #334155;
  }

  /* --- 执行摘要与用户信息文字颜色（暗色模式下使用深色文字，与亮色背景形成高对比） --- */
  .text-gray-400 {
    color: #334155;
  }
  .text-gray-600 {
    color: #1e293b;
  }
  .text-gray-700 {
    color: #0f172a;
  }
  .text-gray-500 {
    color: #475569;
  }
  .text-gray-800 {
    color: #111827;
  }

  /* --- 状态点颜色（暗色背景下加深） --- */
  .bg-blue-500 {
    background-color: #3b82f6;
  }
  .bg-green-500 {
    background-color: #22c55e;
  }
  .bg-red-500 {
    background-color: #ef4444;
  }
  .bg-gray-400 {
    background-color: #94a3b8;
  }

  /* --- 推理区域 --- */
  .bg-amber-50 {
    background-color: rgba(180, 130, 30, 0.15);
  }
  .border-amber-200 {
    border-color: rgba(180, 130, 30, 0.3);
  }
  .text-amber-800 {
    color: #fbbf24;
  }
  .text-amber-600 {
    color: #f59e0b;
  }
  .text-amber-500 {
    color: #f59e0b;
  }

  /* --- 回复区域背景（暗色模式下与明细模式 agent response 对齐：绿色调浅背景） --- */
  .bg-white {
    background-color: rgba(34, 197, 94, 0.1);
  }
  .border-l-4 {
    border-left-width: 4px;
  }
  .border-green-500 {
    border-left-color: #22c55e;
  }

  /* --- Todo 列表（与 ChatMessageItem 的 params-inner / params-todo-name 对齐） --- */
  .params-inner {
    background-color: #f1f5f9;
    border-color: rgba(255, 255, 255, 0.1);
  }
  .params-todo-name {
    color: #1e293b;
  }
}
</style>

<style scoped>
/* ========== 撤销按钮 ========== */
.undo-button {
  color: #f56c6c !important;
  font-size: 12px !important;
  padding: 2px 6px !important;
  border-radius: 4px !important;
  background: rgba(245, 108, 108, 0.1) !important;
  border: 1px solid rgba(245, 108, 108, 0.2) !important;
}

.undo-button:hover {
  background: rgba(245, 108, 108, 0.2) !important;
  color: #f56c6c !important;
  border-color: rgba(245, 108, 108, 0.3) !important;
}

/* ========== Markdown 样式（与 ChatMessageItem 严格一致） ========== */

:deep(.markdown-content) {
  word-wrap: break-word;
  overflow-wrap: break-word;
}

:deep(.markdown-content h1),
:deep(.markdown-content h2),
:deep(.markdown-content h3),
:deep(.markdown-content h4),
:deep(.markdown-content h5),
:deep(.markdown-content h6) {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.25;
}

:deep(.markdown-content h1) {
  font-size: 1.5em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

:deep(.markdown-content h2) {
  font-size: 1.3em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

:deep(.markdown-content h3) {
  font-size: 1.1em;
}

:deep(.markdown-content p) {
  margin-bottom: 1em;
  line-height: 1.6;
}

:deep(.markdown-content ul),
:deep(.markdown-content ol) {
  padding-left: 2em;
  margin-bottom: 1em;
}

:deep(.markdown-content li) {
  margin-bottom: 0.25em;
}

:deep(.markdown-content blockquote) {
  margin: 1em 0;
  padding: 0 1em;
  color: #6a737d;
  border-left: 0.25em solid #dfe2e5;
  background-color: #f6f8fa;
  padding: 0.5em 1em;
  border-radius: 0 4px 4px 0;
}

:deep(.markdown-content code) {
  font-family:
    ui-monospace,
    SFMono-Regular,
    SF Mono,
    Menlo,
    Consolas,
    Liberation Mono,
    monospace;
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}

:deep(.markdown-content pre) {
  background-color: #f6f8fa;
  border-radius: 6px;
  padding: 1em;
  overflow: auto;
  margin: 1em 0;
}

:deep(.markdown-content pre code) {
  background-color: transparent;
  padding: 0;
  font-size: 0.8em;
  line-height: 1.45;
}

:deep(.markdown-content table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
}

:deep(.markdown-content table th),
:deep(.markdown-content table td) {
  border: 1px solid #dfe2e5;
  padding: 0.6em 1em;
}

:deep(.markdown-content table th) {
  font-weight: 600;
  background-color: #f6f8fa;
}

:deep(.markdown-content tr:nth-child(2n)) {
  background-color: #f6f8fa;
}

:deep(.markdown-content a) {
  color: #0366d6;
  text-decoration: none;
}

:deep(.markdown-content a:hover) {
  text-decoration: underline;
}

:deep(.markdown-content img) {
  max-width: 100%;
  height: auto;
}

:deep(.markdown-content hr) {
  height: 0.25em;
  padding: 0;
  margin: 1.5em 0;
  background-color: #e1e4e8;
  border: 0;
}

:deep(.markdown-content strong) {
  font-weight: 600;
}

:deep(.markdown-content em) {
  font-style: italic;
}

:deep(.markdown-content del) {
  text-decoration: line-through;
}

/* ========== 暗色模式（与 ChatMessageItem 严格一致） ========== */
@media (prefers-color-scheme: dark) {
  /* --- Markdown（与 ChatMessageItem 完全一致） --- */
  :deep(.markdown-content h1),
  :deep(.markdown-content h2),
  :deep(.markdown-content h3),
  :deep(.markdown-content h4),
  :deep(.markdown-content h5),
  :deep(.markdown-content h6) {
    color: #0f172a;
    border-bottom-color: #cbd5e1;
  }

  :deep(.markdown-content blockquote) {
    color: #334155;
    border-left-color: #64748b;
    background-color: #e2e8f0;
  }

  :deep(.markdown-content table th) {
    background-color: #cbd5e1;
    font-weight: 700;
    color: #0f172a;
  }

  :deep(.markdown-content a) {
    color: #1d4ed8;
  }

  /* --- 卡片分隔线 --- */
  .border-gray-100 {
    border-color: #334155;
  }
  .border-b-gray-100 {
    border-bottom-color: #334155;
  }

  /* --- 执行摘要与用户信息文字颜色（暗色模式下使用深色文字，与亮色背景形成高对比） --- */
  .text-gray-400 {
    color: #334155;
  }
  .text-gray-600 {
    color: #1e293b;
  }
  .text-gray-700 {
    color: #0f172a;
  }
  .text-gray-500 {
    color: #475569;
  }
  .text-gray-800 {
    color: #111827;
  }

  /* --- 状态点颜色（暗色背景下加深） --- */
  .bg-blue-500 {
    background-color: #3b82f6;
  }
  .bg-green-500 {
    background-color: #22c55e;
  }
  .bg-red-500 {
    background-color: #ef4444;
  }
  .bg-gray-400 {
    background-color: #94a3b8;
  }

  /* --- 推理区域 --- */
  .bg-amber-50 {
    background-color: rgba(180, 130, 30, 0.15);
  }
  .border-amber-200 {
    border-color: rgba(180, 130, 30, 0.3);
  }
  .text-amber-800 {
    color: #fbbf24;
  }
  .text-amber-600 {
    color: #f59e0b;
  }
  .text-amber-500 {
    color: #f59e0b;
  }

  /* --- 回复区域背景（暗色模式下与明细模式 agent response 对齐：绿色调浅背景） --- */
  .bg-white {
    background-color: rgba(34, 197, 94, 0.1);
  }
  .border-l-4 {
    border-left-width: 4px;
  }
  .border-green-500 {
    border-left-color: #22c55e;
  }

  /* --- Todo 列表（与 ChatMessageItem 的 params-inner / params-todo-name 对齐） --- */
  .params-inner {
    background-color: #f1f5f9;
    border-color: rgba(255, 255, 255, 0.1);
  }
  .params-todo-name {
    color: #1e293b;
  }
}

@keyframes pulse-border {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.animate-pulse-border {
  animation: pulse-border 1.5s ease-in-out infinite;
}
</style>
