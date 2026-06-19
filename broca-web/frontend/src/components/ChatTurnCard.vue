<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useChatStore, useSocketStore } from '@/stores'
import { renderMarkdown } from '@/utils/markdown'

const chatStore = useChatStore()
const socketStore = useSocketStore()
import { sessionApi } from '@/api/session'

interface ToolCallStat {
  toolName: string
  count: number
}

interface TodoItem {
  name: string
  status: 'pending' | 'in_progress' | 'completed'
}

interface ChangedFileInfo {
  totalAdded: number
  totalDeleted: number
  totalModified: number
  filesAdded: string[]
  filesDeleted: string[]
  filesModified: string[]
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
  changedFiles: ChangedFileInfo | null
}

const props = defineProps<{
  turn: TurnSummary
  consecutiveAgent: boolean
}>()

// 折叠状态：推理内容
const showReasoning = ref(false)
// 悬停显示操作按钮
const showActions = ref(false)
// 折叠状态：长回复（超过 25 行）
const showFullResponse = ref(false)
const MAX_RESPONSE_LINES = 25
const isLongResponse = computed(() => {
  const text = props.turn.finalResponse
  if (!text) return false
  return text.split('\n').length > MAX_RESPONSE_LINES
})

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
    active: 'border-l-active',
    completed: 'border-l-completed',
    error: 'border-l-error',
  }
  return map[simplifiedStatus.value] || 'border-l-completed'
})

const headerTextClass = computed(() => {
  if (simplifiedStatus.value === 'completed') return 'text-agent'
  if (simplifiedStatus.value === 'error') return 'text-error'
  return 'text-gray-700'
})

const statusColorClass = computed(() => {
  const map: Record<string, string> = {
    active: 'text-active',
    completed: 'text-completed',
    error: 'text-error',
  }
  return map[simplifiedStatus.value] || 'text-gray-600'
})

const statusDotClass = computed(() => {
  const map: Record<string, string> = {
    active: 'dot-active animate-pulse',
    completed: 'dot-completed',
    error: 'dot-error',
  }
  return map[simplifiedStatus.value] || 'dot-completed'
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

// 是否显示文件变更
const showChangedFiles = computed(() => {
  const cf = props.turn.changedFiles
  return cf && (cf.totalAdded > 0 || cf.totalDeleted > 0 || cf.totalModified > 0)
})

// 文件变更详情展开/折叠
const showChangedFilesDetail = ref(false)
const toggleChangedFiles = () => {
  showChangedFilesDetail.value = !showChangedFilesDetail.value
}

// ====== 文件 Diff 弹窗 ======
const diffDialogVisible = ref(false)
const diffContent = ref('')
const diffFileName = ref('')
const diffLoading = ref(false)

const openFileDiff = async (filePath: string) => {
  if (!chatStore.sessionId) return
  diffFileName.value = filePath
  diffDialogVisible.value = true
  diffLoading.value = true
  diffContent.value = ''
  try {
    const turnId = props.turn.turnId
    const res = await sessionApi.getFileDiff(chatStore.sessionId, turnId, filePath)
    diffContent.value = res.diff || ''
  } catch (err) {
    diffContent.value = ''
    console.error('Failed to get file diff:', err)
  } finally {
    diffLoading.value = false
  }
}

// 解析 unified diff 为带颜色的行
interface DiffLine { text: string; type: 'add' | 'del' | 'ctx' | 'head' }
const parsedDiffLines = computed<DiffLine[]>(() => {
  if (!diffContent.value) return [{ text: '(无变更)', type: 'ctx' }]
  const lines: DiffLine[] = []
  for (const raw of diffContent.value.split('\n')) {
    if (raw.startsWith('+') && !raw.startsWith('+++')) {
      lines.push({ text: raw.slice(1), type: 'add' })
    } else if (raw.startsWith('-') && !raw.startsWith('---')) {
      lines.push({ text: raw.slice(1), type: 'del' })
    } else if (raw.startsWith('@@')) {
      lines.push({ text: raw, type: 'head' })
    } else {
      lines.push({ text: raw, type: 'ctx' })
    }
  }
  return lines
})

// 是否有工具执行（无工具执行时隐藏整个执行摘要）
const hasToolExecution = computed(() => {
  return showToolStats.value || !!currentToolText.value || showFilePath.value || showTodoList.value || showChangedFiles.value
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
    (props.turn.status === 'completed' || props.turn.status === 'error') &&
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
      'turn-card',
      statusBorderClass,
      consecutiveAgent ? 'mt-1' : 'mt-3',
    ]"
    @mouseenter="showActions = true"
    @mouseleave="showActions = false"
  >
    <!-- 标题栏 -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-2 mb-2">
      <div class="flex items-center gap-2 w-full sm:w-auto">
        <span :class="['inline-block w-2.5 h-2.5 rounded-full flex-shrink-0', statusDotClass]"></span>
        <span class="font-semibold text-sm truncate" :class="headerTextClass">{{ turn.agentName }}</span>
        <span class="text-xs text-gray-600 flex-shrink-0">第{{ turn.sequenceNumber }}轮</span>
        <span class="stat-status text-xs ml-auto flex-shrink-0" :class="statusColorClass">{{ statusText }}</span>
      </div>
      <div class="flex items-center gap-2 text-xs header-right justify-end sm:justify-start">
        <span v-if="formattedCompletionTime" class="text-gray-500">🕐 {{ formattedCompletionTime }}</span>
        <span class="text-gray-500">⏱️ {{ formattedDuration }}</span>
      </div>
    </div>

    <!-- 用户消息 -->
    <div v-if="turn.userMessage" class="section-accent accent-user">
      <div class="flex items-start gap-2 text-xs sm:text-sm text-gray-600">
        <span class="flex-shrink-0">👤</span>
        <div>{{ turn.userMessage }}</div>
      </div>
    </div>

    <!-- 执行摘要 -->
    <div v-if="hasToolExecution" class="section-accent accent-tool">
      <div class="summary-header">
        <span class="summary-title">执行摘要</span>
      </div>
      <div class="summary-body">
        <div class="summary-row">
          <span class="summary-label">📋 步骤</span>
          <span class="summary-value">{{ turn.totalSteps }}</span>
        </div>
        <div v-if="showTodoList" class="summary-row todo-section">
          <div class="todo-header">
            <span class="summary-label">📝 任务</span>
          </div>
          <div class="todo-list">
            <div v-for="(todo, idx) in turn.currentTodoList" :key="idx" class="todo-item-inner">
              <div class="todo-item-row">
                <span class="todo-icon">
                  <span v-if="todo.status === 'completed'">✅</span>
                  <span v-else-if="todo.status === 'in_progress'">⏳</span>
                  <span v-else>⬜️</span>
                </span>
                <span class="todo-name">{{ todo.name }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="showToolStats" class="summary-row">
          <span class="summary-label">🔧 工具调用</span>
          <span class="summary-value stats-text">{{ toolStatsText }}</span>
        </div>
        <!-- 变更文件 -->
        <div v-if="showChangedFiles" class="summary-row">
          <span class="summary-label">📁 变更文件</span>
          <span class="summary-value changed-files-summary" @click="toggleChangedFiles">
            <span class="cf-added">+{{ turn.changedFiles.totalAdded }}</span>
            <span class="cf-sep"> </span>
            <span class="cf-deleted">-{{ turn.changedFiles.totalDeleted }}</span>
            <span class="cf-sep"> </span>
            <span class="cf-modified">~{{ turn.changedFiles.totalModified }}</span>
            <span class="cf-expand-icon">{{ showChangedFilesDetail ? '▲' : '▼' }}</span>
          </span>
        </div>
        <div v-if="showChangedFiles && showChangedFilesDetail" class="changed-files-detail">
          <div v-if="turn.changedFiles.filesAdded.length" class="cf-group">
            <div class="cf-group-label cf-added-label">新增</div>
            <div v-for="f in turn.changedFiles.filesAdded" :key="f" class="cf-file-item cf-added-file">
              <span class="cf-file-link" @click="openFileDiff(f)" title="查看 diff">+ {{ f }}</span>
            </div>
          </div>
          <div v-if="turn.changedFiles.filesDeleted.length" class="cf-group">
            <div class="cf-group-label cf-deleted-label">删除</div>
            <div v-for="f in turn.changedFiles.filesDeleted" :key="f" class="cf-file-item cf-deleted-file">
              <span class="cf-file-link" @click="openFileDiff(f)" title="查看 diff">- {{ f }}</span>
            </div>
          </div>
          <div v-if="turn.changedFiles.filesModified.length" class="cf-group">
            <div class="cf-group-label cf-modified-label">修改</div>
            <div v-for="f in turn.changedFiles.filesModified" :key="f" class="cf-file-item cf-modified-file">
              <span class="cf-file-link" @click="openFileDiff(f)" title="查看 diff">~ {{ f }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 回复区域 -->
    <div v-if="showResponse" class="section-accent accent-agent">
      <div class="flex items-start gap-2">
        <span class="flex-shrink-0 text-sm mt-0.5">🤖</span>
        <div class="flex-1 min-w-0">
          <div class="markdown-content text-gray-800 text-xs sm:text-sm leading-relaxed overflow-x-auto"
            :class="{ 'response-collapsed': isLongResponse && !showFullResponse }"
            v-html="renderMarkdown(turn.finalResponse)"></div>
          <!-- 渐变遮罩由 .response-collapsed::after 处理 -->
          <button
            v-if="isLongResponse"
            class="expand-btn"
            @click="showFullResponse = !showFullResponse"
          >
            {{ showFullResponse ? '收起 ▲' : '展开 ▼' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 当前调用（琥珀色） -->
    <div v-if="currentToolText && simplifiedStatus === 'active'" class="pt-2">
      <div class="tool-call-badge">
        <span class="text-sm animate-pulse">⏳</span>
        <span class="text-gray-500">当前调用:</span>
        <span class="font-semibold">{{ currentToolText }}</span>
      </div>
    </div>
    <!-- 未调用工具时：展示思考（可折叠） -->
    <div v-else-if="hasReasoning" class="pt-2">
      <button
        class="reasoning-toggle"
        @click="showReasoning = !showReasoning"
      >
        <span>{{ showReasoning ? '▼' : '▶' }}</span>
        <span class="reasoning-label">思考</span>
        <span v-if="!showReasoning && simplifiedStatus === 'active'" class="reasoning-dots">...</span>
      </button>
      <div v-if="showReasoning" class="reasoning-content">
        <pre class="reasoning-text">{{ turn.reasoningContent }}</pre>
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

  <!-- Diff 弹窗 -->
  <el-dialog
    v-model="diffDialogVisible"
    :title="'Diff: ' + diffFileName"
    width="80%"
    top="5vh"
    destroy-on-close
  >
    <div v-if="diffLoading" style="text-align:center;padding:40px;">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <p style="margin-top:8px;color:#999;">加载中...</p>
    </div>
    <div v-else class="diff-view">
      <div
        v-for="(line, idx) in parsedDiffLines"
        :key="idx"
        :class="['diff-line', line.type]"
      ><span class="diff-line-num">{{ idx + 1 }}</span><span class="diff-line-content">{{ line.text }}</span></div>
    </div>
  </el-dialog>
</template>


<style scoped>
/* ==================== 卡片基础样式 ==================== */
.turn-card {
  border-radius: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border-color, #e0e0e0);
  border-left-width: 4px;
  border-left-style: solid;
  transition: all 0.2s ease;
  background: var(--card-bg, #ffffff);
}

.turn-card:hover {
  border-color: var(--focus-border, #007acc);
}

/* 状态边框颜色 */
.border-l-active { border-left-color: #5a8fc9; }
.border-l-completed { border-left-color: var(--border-color, #b0b0b0); }
.border-l-error { border-left-color: #c95a5a; }

/* 状态文字颜色 */
.text-active { color: #5a8fc9; }
.text-completed { color: var(--text-secondary, #808080); }
.text-error { color: #c95a5a; }
.text-agent { color: #5a8fc9; }

/* 状态圆点 */
.dot-active { background-color: #5a8fc9; }
.dot-completed { background-color: var(--border-color, #b0b0b0); }
.dot-error { background-color: #c95a5a; }

.dot-active.animate-pulse {
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ==================== 标题栏 ==================== */
.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-status {
  font-weight: 500;
  font-size: 11px;
  white-space: nowrap;
}



/* ==================== 区域分隔 + 左侧标识竖线 ==================== */
.section-accent {
  padding: 8px 0 8px 10px;
  border-left: 2px solid transparent;
  margin-top: 8px;
  border-bottom: 1px solid var(--border-color, #e0e0e0);
}

.section-accent:last-child {
  border-bottom: none;
}

.accent-user {
  border-left-color: var(--text-secondary, #8e8e8e);
}

.accent-tool {
  border-left-color: #c9a84c;
}

.accent-agent {
  border-left-color: #5a8fc9;
}

/* ==================== 工具调用琥珀色 ==================== */
.tool-call-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(201, 168, 76, 0.1);
  border: 1px solid rgba(201, 168, 76, 0.25);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-primary, #333);
}

.tool-call-badge .font-semibold {
  font-weight: 600;
}

/* ==================== 推理内容 ==================== */
.reasoning-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--warning-fg, #b89500);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 0;
}

.reasoning-toggle:hover {
  color: var(--warning-fg, #d97706);
}

.reasoning-label {
  font-size: 12px;
}

.reasoning-dots {
  animation: pulse-dot 1.5s ease-in-out infinite;
  font-size: 12px;
}

.reasoning-content {
  margin-top: 6px;
  padding: 8px 12px;
  border-left: 3px solid var(--warning-fg, #b89500);
  border-radius: 4px;
}

.reasoning-text {
  margin: 0;
  font-family: var(--code-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 11px;
  color: var(--warning-fg, #b89500);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

/* ==================== 执行摘要 ==================== */
.summary-header {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-secondary, #64748b);
  margin-bottom: 6px;
}

.summary-title {
  font-weight: 500;
}

.summary-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}

.summary-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.summary-label {
  color: var(--text-primary, #333);
  flex-shrink: 0;
  min-width: 64px;
  font-size: 12px;
}

.summary-value {
  color: var(--text-secondary, #64748b);
  font-size: 12px;
}

.stats-text {
  word-break: break-word;
}

.todo-section {
  flex-direction: column;
}

.todo-header {
  display: flex;
  align-items: center;
}

.todo-item-inner {
  margin-bottom: 4px;
}

.todo-item-inner:last-child {
  margin-bottom: 0;
}

.todo-item-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.todo-icon {
  font-size: 13px;
  line-height: 1.5;
}

.todo-name {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
  font-weight: 500;
}

/* ==================== Todo 列表 ==================== */
.todo-list {
  padding: 6px 8px;
  border: 1px solid rgba(201, 168, 76, 0.25);
  border-radius: 4px;
  background: rgba(201, 168, 76, 0.06);
  margin-left: 20px;
}

/* ==================== 变更文件 ==================== */
.changed-files-summary {
  cursor: pointer;
  user-select: none;
}

.changed-files-summary:hover {
  opacity: 0.8;
}

.cf-added { color: #16a34a; font-weight: 600; }
.cf-deleted { color: #dc2626; font-weight: 600; }
.cf-modified { color: #ca8a04; font-weight: 600; }
.cf-sep { margin: 0 2px; }
.cf-expand-icon {
  font-size: 10px;
  margin-left: 4px;
  color: var(--text-secondary, #64748b);
}

.changed-files-detail {
  margin-top: 4px;
  margin-left: 70px;
  padding: 6px 8px;
  border: 1px solid rgba(201, 168, 76, 0.25);
  border-radius: 4px;
  background: rgba(201, 168, 76, 0.06);
  font-size: 11px;
}

.cf-group {
  margin-bottom: 4px;
}

.cf-group:last-child {
  margin-bottom: 0;
}

.cf-group-label {
  font-weight: 600;
  font-size: 11px;
  margin-bottom: 2px;
}

.cf-added-label { color: #16a34a; }
.cf-deleted-label { color: #dc2626; }
.cf-modified-label { color: #ca8a04; }

.cf-file-item {
  padding: 1px 0 1px 8px;
  font-family: var(--code-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 11px;
  color: var(--text-secondary, #64748b);
  word-break: break-all;
}

.cf-added-file { color: #15803d; }
.cf-deleted-file { color: #b91c1c; }
.cf-modified-file { color: #a16207; }

.cf-file-link {
  cursor: pointer;
  text-decoration: none;
  border-bottom: 1px dashed currentColor;
}

.cf-file-link:hover {
  opacity: 0.7;
}

/* ==================== Diff 弹窗 ==================== */
.diff-view {
  background: #f8f9fa;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  max-height: 70vh;
  overflow: auto;
}

.diff-line {
  display: flex;
  padding: 0 8px;
  min-height: 1.6em;
  width: max-content;
  min-width: 100%;
}

.diff-line-num {
  display: inline-block;
  width: 32px;
  flex-shrink: 0;
  text-align: right;
  color: #999;
  padding-right: 12px;
  user-select: none;
}

.diff-line-content {
  white-space: pre;
  flex: 1;
}

.diff-line.add { background: #e6ffec; }
.diff-line.del { background: #ffebe9; }
.diff-line.head { background: #f0f0f0; color: #666; font-weight: 600; }
.diff-line.ctx { color: #333; }

.diff-line.add .diff-line-content { color: #055d20; }
.diff-line.del .diff-line-content { color: #82071e; }

/* ==================== 展开按钮 ==================== */
.expand-btn {
  display: inline-block;
  margin-top: 4px;
  background: transparent;
  border: none;
  color: var(--text-link, #006ab1);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 3px;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.15s ease;
}

.expand-btn:hover {
  opacity: 1;
  background: transparent;
}

/* ==================== 撤销按钮 ==================== */
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

/* ==================== Markdown 样式 ==================== */
:deep(.markdown-content) {
  word-wrap: break-word;
  overflow-wrap: break-word;
  color: var(--text-primary, #333);
  font-size: 13px;
  line-height: 1.6;
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
  color: #1e293b;
}

:deep(.markdown-content h1) { font-size: 1.5em; border-bottom: 1px solid var(--border-color, #eaecef); padding-bottom: 0.3em; }
:deep(.markdown-content h2) { font-size: 1.3em; border-bottom: 1px solid var(--border-color, #eaecef); padding-bottom: 0.3em; }
:deep(.markdown-content h3) { font-size: 1.1em; }
:deep(.markdown-content p) { margin-bottom: 1em; line-height: 1.6; }
:deep(.markdown-content ul),
:deep(.markdown-content ol) { padding-left: 2em; margin-bottom: 1em; }
:deep(.markdown-content li) { margin-bottom: 0.25em; }
:deep(.markdown-content blockquote) {
  margin: 1em 0;
  padding: 0.5em 1em;
  color: var(--text-secondary, #6a737d);
  border-left: 0.25em solid var(--border-color, #dfe2e5);
  background: var(--bg-tertiary, #f6f8fa);
  border-radius: 0 4px 4px 0;
}
:deep(.markdown-content code) {
  font-family: var(--code-font-family, ui-monospace, SFMono-Regular, monospace);
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}
:deep(.markdown-content pre) {
  background: var(--bg-tertiary, #f6f8fa);
  border: 1px solid var(--border-color, #e1e4e8);
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
  border: 1px solid var(--border-color, #dfe2e5);
  padding: 0.6em 1em;
}
:deep(.markdown-content table th) {
  font-weight: 600;
  background: var(--bg-tertiary, #f6f8fa);
  color: #1e293b;
}
:deep(.markdown-content a) { color: var(--text-link, #0366d6); text-decoration: none; }
:deep(.markdown-content a:hover) { text-decoration: underline; }
:deep(.markdown-content img) { max-width: 100%; height: auto; }
:deep(.markdown-content hr) { height: 0.25em; padding: 0; margin: 1.5em 0; background-color: var(--border-color, #e1e4e8); border: 0; }
:deep(.markdown-content strong) { font-weight: 600; }
:deep(.markdown-content em) { font-style: italic; }

/* ==================== 响应渐变遮罩 ==================== */
.response-collapsed {
  max-height: calc(1.5em * 25);
  overflow: hidden;
  position: relative;
}

.response-collapsed::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3em;
  background: linear-gradient(transparent, var(--card-bg, #ffffff));
  pointer-events: none;
}
</style>
