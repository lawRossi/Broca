<script setup lang="ts">
import { ref, computed } from 'vue'
import { marked } from 'marked'
import type { TurnSummary } from '../stores/chat'
import { useChatStore } from '../stores/chat'
import { postMessage, onMessage, getInitialData } from '../api/vscode'

const props = defineProps<{
  turn: TurnSummary
  consecutiveAgent: boolean
}>()

const chatStore = useChatStore()

// Configure marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

// ==================== 展开状态 ====================
const showReasoning = ref(false)
const showActions = ref(false)
const showUndoConfirm = ref(false)
const showFullResponse = ref(false)
const MAX_RESPONSE_LINES = 25

// ==================== 长回复检测 ====================
const isLongResponse = computed(() => {
  const text = props.turn.finalResponse
  if (!text) return false
  let lineCount = 0
  let pos = 0
  while (pos < text.length) {
    const nextBreak = text.indexOf('\n', pos)
    if (nextBreak === -1) {
      lineCount++
      break
    }
    lineCount++
    pos = nextBreak + 1
    if (lineCount > MAX_RESPONSE_LINES) return true
  }
  return false
})

// ==================== 长用户输入检测（超过 300 字符） ====================
const showFullUserMessage = ref(false)
const MAX_USER_CHARS = 300
const isLongUserMessage = computed(() => {
  const text = props.turn.userMessage
  if (!text) return false
  return text.length > MAX_USER_CHARS
})

// ==================== 状态文本与颜色（与 web 版一致） ====================
const simplifiedStatus = computed(() => {
  if (props.turn.status === 'completed') return 'completed'
  if (props.turn.status === 'error') return 'error'
  return 'active'  // active / thinking / calling_tool 统一为"进行中"
})

const statusText = computed(() => {
  if (simplifiedStatus.value === 'completed') return '已完成'
  if (simplifiedStatus.value === 'error') return '中断'
  return '进行中'
})

const statusBorderClass = computed(() => {
  if (simplifiedStatus.value === 'active') return 'border-l-blue'
  if (simplifiedStatus.value === 'error') return 'border-l-red'
  return 'border-l-green'
})

const headerTextClass = computed(() => {
  if (simplifiedStatus.value === 'completed') return 'text-blue'
  if (simplifiedStatus.value === 'error') return 'text-red'
  return 'text-primary'
})

const statusColorClass = computed(() => {
  if (simplifiedStatus.value === 'active') return 'text-blue'
  if (simplifiedStatus.value === 'error') return 'text-red'
  return 'text-green'
})

const statusDotClass = computed(() => {
  if (simplifiedStatus.value === 'active') return 'dot-blue pulse'
  if (simplifiedStatus.value === 'error') return 'dot-red'
  return 'dot-gray'
})

// ==================== 耗时格式化（与 web 版一致） ====================
const formattedDuration = computed(() => {
  const seconds = Math.round(props.turn.totalDuration)
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}分${secs}秒`
})

// 完成时刻（用 startedAt + totalDuration 算出结束时间）
const formattedCompletionTime = computed(() => {
  if (props.turn.status !== 'completed') return ''
  const endMs = props.turn.startedAt + props.turn.totalDuration * 1000
  const d = new Date(endMs)
  const now = new Date()
  const pad = (n: number) => n.toString().padStart(2, '0')
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  if (
    d.getFullYear() !== now.getFullYear() ||
    d.getMonth() !== now.getMonth() ||
    d.getDate() !== now.getDate()
  ) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
  }
  return time
})

// ==================== 执行摘要计算属性（对齐 web 版） ====================
const currentToolText = computed(() => props.turn.currentTool || '')

// 文件路径只在 read/edit/write_file 工具时显示（与 web 版一致）
const showFilePath = computed(() => {
  return props.turn.currentFilePath &&
    props.turn.currentTool &&
    ['read_file', 'edit_file', 'write_file'].includes(props.turn.currentTool)
})

const showTodoList = computed(() => {
  return props.turn.currentTodoList.length > 0
})

const showToolStats = computed(() => {
  return props.turn.toolCallStats.length > 0
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

const hasToolExecution = computed(() => {
  return showToolStats.value || !!currentToolText.value || showFilePath.value || showTodoList.value || showChangedFiles.value
})

const toolStatsText = computed(() => {
  return props.turn.toolCallStats.map(s => `${s.toolName} (${s.count}次)`).join(', ')
})

// ==================== 文件 Diff ====================
const diffDialogVisible = ref(false)
const diffContent = ref('')
const diffFileName = ref('')
const diffLoading = ref(false)

interface DiffLine { text: string; type: 'add' | 'del' | 'ctx' | 'head'; lineNum: number | null }
const parsedDiffLines = computed<DiffLine[]>(() => {
  if (!diffContent.value) return [{ text: '(无变更)', type: 'ctx', lineNum: null }]
  const lines: DiffLine[] = []
  let newLineNum = 0
  for (const raw of diffContent.value.split('\n')) {
    // 跳过 git metadata 行
    if (
      raw.startsWith('diff --git') ||
      raw.startsWith('index ') ||
      raw.startsWith('--- ') ||
      raw.startsWith('+++ ') ||
      raw.startsWith('new file mode') ||
      raw.startsWith('deleted file mode') ||
      raw.startsWith('old mode') ||
      raw.startsWith('new mode') ||
      raw.startsWith('rename from') ||
      raw.startsWith('rename to') ||
      raw.startsWith('copy from') ||
      raw.startsWith('copy to') ||
      raw.startsWith('similarity index') ||
      raw.startsWith('Binary files')
    ) continue

    if (raw.startsWith('@@')) {
      // @@ 头部：仅解析行号，不展示
      const match = raw.match(/@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/)
      if (match) newLineNum = parseInt(match[1])
      continue
    }
    if (raw.startsWith('+')) {
      lines.push({ text: raw.slice(1), type: 'add', lineNum: newLineNum })
      newLineNum++
    } else if (raw.startsWith('-')) {
      lines.push({ text: raw.slice(1), type: 'del', lineNum: null })
    } else {
      lines.push({ text: raw, type: 'ctx', lineNum: newLineNum })
      newLineNum++
    }
  }
  return lines
})

const openFileDiff = (filePath: string) => {
  diffFileName.value = filePath
  diffDialogVisible.value = true
  diffLoading.value = true
  diffContent.value = ''
  // 通过 extension host 获取 diff（extension host 有正确的 API base URL）
  const unsub = onMessage((data: any) => {
    if (data.type === 'fileDiffResult' && data.payload?.filePath === filePath) {
      diffContent.value = data.payload.diff || ''
      diffLoading.value = false
      unsub()
    }
  })
  postMessage({
    type: 'viewDiff',
    payload: {
      sessionId: chatStore.sessionId,
      turnId: props.turn.turnId,
      filePath,
    },
  })
  // 超时保护
  setTimeout(() => {
    if (diffLoading.value) {
      diffLoading.value = false
      diffContent.value = ''
    }
  }, 15000)
}

// ==================== 回复区域 ====================
const showResponse = computed(() => props.turn.finalResponse.length > 0)
const hasReasoning = computed(() => props.turn.reasoningContent.length > 0)

// ==================== Markdown 渲染（复用 marked） ====================
const renderedResponse = computed(() => {
  if (!props.turn.finalResponse) return ''
  try {
    return marked.parse(props.turn.finalResponse) as string
  } catch {
    return props.turn.finalResponse
  }
})

// ==================== 撤销功能 ====================
const canUndo = computed(() => {
  if (!chatStore.connected || !chatStore.sessionId || !chatStore.runnerAlive) return false
  if (props.turn.status !== 'completed' && props.turn.status !== 'error') return false
  return !!props.turn.lastMessageId
})

function handleUndo() {
  showUndoConfirm.value = true
}

function confirmUndo() {
  showUndoConfirm.value = false
  if (props.turn.lastMessageId) {
    chatStore.sendUndo(props.turn.lastMessageId, 'turn', props.turn.agentId)
  }
}

function cancelUndo() {
  showUndoConfirm.value = false
}

// ==================== 连续 agent 判断 ====================
const showAgentHeader = computed(() => !props.consecutiveAgent)
</script>

<template>
  <div
    :class="['turn-card', statusBorderClass, { 'card-compact': consecutiveAgent }]"
    @mouseenter="showActions = true"
    @mouseleave="showActions = false"
  >
    <!-- ==================== 标题栏（对齐 web 版） ==================== -->
    <div class="turn-header">
      <div class="header-left">
        <span :class="['status-dot', statusDotClass]"></span>
        <span class="agent-name" :class="headerTextClass">{{ turn.agentName }}</span>
        <span class="turn-label">第{{ turn.sequenceNumber }}轮</span>
      </div>
      <div class="header-right">
        <span :class="['header-stat', 'stat-status', statusColorClass]">{{ statusText }}</span>
        <span class="header-sep">|</span>
        <span v-if="formattedCompletionTime" class="completion-time" :title="'完成于 ' + formattedCompletionTime">🕐 {{ formattedCompletionTime }}</span>
        <span class="duration">⏱️ {{ formattedDuration }}</span>
      </div>
    </div>

    <!-- ==================== 用户消息（对齐 web 版） ==================== -->
    <div v-if="turn.userMessage" class="user-message-section section-accent accent-user">
      <div class="user-message-row">
        <span class="user-icon">👤</span>
        <div class="user-message-text" :class="{ 'user-msg-collapsed': isLongUserMessage && !showFullUserMessage }">{{ turn.userMessage }}</div>
      </div>
      <button
        v-if="isLongUserMessage"
        class="expand-btn"
        @click="showFullUserMessage = !showFullUserMessage"
      >
        {{ showFullUserMessage ? '收起 ▲' : '展开 ▼' }}
      </button>
    </div>

    <!-- ==================== 执行摘要（对齐 web 版结构） ==================== -->
    <div v-if="hasToolExecution" class="execution-summary section-accent accent-tool">
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
              <span class="cf-file-link" @click="openFileDiff(f)" title="查看 diff">{{ f }}</span>
            </div>
          </div>
          <div v-if="turn.changedFiles.filesDeleted.length" class="cf-group">
            <div class="cf-group-label cf-deleted-label">删除</div>
            <div v-for="f in turn.changedFiles.filesDeleted" :key="f" class="cf-file-item cf-deleted-file">
              <span class="cf-file-link" @click="openFileDiff(f)" title="查看 diff">{{ f }}</span>
            </div>
          </div>
          <div v-if="turn.changedFiles.filesModified.length" class="cf-group">
            <div class="cf-group-label cf-modified-label">修改</div>
            <div v-for="f in turn.changedFiles.filesModified" :key="f" class="cf-file-item cf-modified-file">
              <span class="cf-file-link" @click="openFileDiff(f)" title="查看 diff">{{ f }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 回复区域（对齐 web 版） ==================== -->
    <div v-if="showResponse" class="response-section section-accent accent-agent">
      <div class="response-row">
        <span class="response-icon">🤖</span>
        <div class="response-content">
          <div
            class="markdown-body"
            :class="{ 'response-collapsed': isLongResponse && !showFullResponse }"
            v-html="renderedResponse"
          ></div>
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

    <!-- ==================== 当前调用（与工具名同一行，不显示文件路径） ==================== -->
    <div v-if="currentToolText && simplifiedStatus === 'active'" class="tool-calling-section">
      <div class="tool-calling-row">
        <span class="tool-calling-icon">⏳</span>
        <span class="tool-calling-name">当前调用:</span>
        <span class="tool-calling-name font-semibold">{{ currentToolText }}</span>
      </div>
    </div>
    <!-- 未调用工具时：展示思考（可折叠） -->
    <div v-else-if="hasReasoning" class="reasoning-section">
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

    <!-- ==================== 悬停撤销按钮（底部右对齐，对齐 web 版） ==================== -->
    <div v-if="showActions && canUndo" class="undo-section">
      <button class="undo-btn" @click.stop="handleUndo" title="撤销此轮操作">↩️ 撤销</button>
    </div>

    <!-- ==================== 撤销确认弹窗 ==================== -->
    <Teleport to="body">
      <div v-if="showUndoConfirm" class="dialog-overlay" @click.self="cancelUndo">
        <div class="confirm-dialog">
          <div class="confirm-title">确认撤销</div>
          <div class="confirm-body">确定要撤销"第{{ turn.sequenceNumber }}轮"操作吗？</div>
          <div class="confirm-footer">
            <button class="btn btn-secondary" @click="cancelUndo">取消</button>
            <button class="btn btn-danger" @click="confirmUndo">确定撤销</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ==================== Diff 弹窗 ==================== -->
    <Teleport to="body">
      <div v-if="diffDialogVisible" class="diff-overlay" @click.self="diffDialogVisible = false">
        <div class="diff-dialog">
          <div class="diff-header">
            <span class="diff-title">Diff: {{ diffFileName }}</span>
            <button class="diff-close" @click="diffDialogVisible = false">✕</button>
          </div>
          <div class="diff-body">
            <div v-if="diffLoading" class="diff-loading">加载中...</div>
            <div v-else class="diff-view">
              <div
                v-for="(line, idx) in parsedDiffLines"
                :key="idx"
                :class="['diff-line', line.type]"
              >
                <span class="diff-line-num">{{ line.lineNum ?? '' }}</span>
                <span class="diff-line-content">{{ line.text }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* ==================== 卡片基础样式 ==================== */
.turn-card {
  background: var(--vscode-editor-background, #ffffff);
  border: 1px solid var(--vscode-widget-border, #e0e0e0);
  border-radius: 8px;
  padding: 10px 14px;
  position: relative;
  border-left-width: 4px;
  border-left-style: solid;
  transition: all 0.2s ease;
  margin-bottom: 12px;
}

.turn-card:hover {
  border-color: var(--vscode-focusBorder, #007acc);
}

.card-compact {
  margin-top: 4px;
}

/* 状态边框颜色 */
.border-l-blue { border-left-color: #5a8fc9; }
.border-l-green { border-left-color: var(--vscode-widget-border, #b0b0b0); }
.border-l-red { border-left-color: #c95a5a; }

/* ==================== 标题栏 ==================== */
.turn-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--vscode-widget-border, #e0e0e0);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.turn-label {
  margin-left: 20px;
  color: var(--vscode-editor-foreground, #333);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.header-stat {
  font-size: 11px;
  white-space: nowrap;
}

.stat-tools {
  color: var(--vscode-descriptionForeground, #808080);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-steps {
  color: var(--vscode-descriptionForeground, #808080);
}

.stat-status {
  font-weight: 500;
}

.header-sep {
  color: var(--vscode-descriptionForeground, #808080);
}

.completion-time {
  color: var(--vscode-editor-foreground, #333);
}

.duration {
  color: var(--vscode-editor-foreground, #333);
}

/* ==================== 区域分隔 + 左侧标识竖线 ==================== */
.section-accent {
  padding: 8px 0 8px 10px;
  border-left: 2px solid transparent;
  margin-top: 8px;
  border-bottom: 1px solid var(--vscode-widget-border, #e0e0e0);
}

.section-accent:last-child {
  border-bottom: none;
}

.accent-user {
  border-left-color: var(--vscode-descriptionForeground, #8e8e8e);
}

.accent-tool {
  border-left-color: #c9a84c;
}

.accent-agent {
  border-left-color: #5a8fc9;
}

/* ==================== 用户消息 ==================== */
.user-message-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: var(--vscode-editor-foreground, #333);
}

.user-message-text {
  word-break: break-word;
  line-height: 1.4;
}

/* ==================== 执行摘要（对齐 web 版结构） ==================== */
.execution-summary {
  /* spacing & border handled by .section-accent */
}

/* 执行摘要 */
.summary-header {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--vscode-descriptionForeground, #808080);
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
  color: var(--vscode-descriptionForeground, #808080);
  flex-shrink: 0;
  min-width: 64px;
  font-size: 12px;
}

.summary-value {
  color: var(--vscode-editor-foreground, #333);
  font-size: 12px;
}

.stats-text {
  word-break: break-word;
}

.todo-header {
  display: flex;
  align-items: center;
}

/* Todo 列表 */
.todo-list {
  margin-left: 64px;
  padding: 6px 8px;
  border: 1px solid rgba(201, 168, 76, 0.25);
  border-radius: 4px;
  background: rgba(201, 168, 76, 0.06);
}

.todo-item-inner {
  margin-bottom: 4px;
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
  color: var(--vscode-descriptionForeground, #808080);
}

.changed-files-detail {
  margin-top: 4px;
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
  font-family: var(--vscode-editor-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 11px;
  color: var(--vscode-descriptionForeground, #808080);
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
  color: var(--vscode-editor-foreground, #333);
  font-weight: 500;
}

/* ==================== 回复区域（对齐 web 版） ==================== */
.response-section {
  /* spacing & border handled by .section-accent */
}

.response-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.response-icon {
  flex-shrink: 0;
  font-size: 14px;
  margin-top: 2px;
}

.response-content {
  flex: 1;
  min-width: 0;
}

.response-collapsed {
  max-height: calc(1.6em * 25);
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
  background: linear-gradient(transparent, var(--vscode-editor-background, #fff));
  pointer-events: none;
}

.expand-btn {
  display: inline-block;
  margin-top: 4px;
  background: transparent;
  border: none;
  color: var(--vscode-textLink-foreground, #006ab1);
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

/* ==================== 推理内容（对齐 web 版） ==================== */
/* ==================== 当前调用工具 ==================== */
.tool-calling-section {
  padding-top: 6px;
}

.tool-calling-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(201, 168, 76, 0.1);
  border: 1px solid rgba(201, 168, 76, 0.25);
  border-radius: 6px;
  font-size: 12px;
}

.tool-calling-label-row {
  color: var(--vscode-descriptionForeground, #808080);
  font-size: 11px;
  font-weight: 500;
  margin-bottom: 2px;
}

.tool-calling-icon {
  font-size: 13px;
  animation: pulse-spin 1.5s ease-in-out infinite;
}

@keyframes pulse-spin {
  0%, 100% { opacity: 1; transform: rotate(0deg); }
  50% { opacity: 0.6; transform: rotate(15deg); }
}

.tool-calling-name {
  color: var(--vscode-editor-foreground, #333);
  font-weight: 600;
}

.tool-calling-file {
  color: var(--vscode-descriptionForeground, #808080);
  font-size: 11px;
  margin-left: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 350px;
}

@media (max-width: 500px) {
  .tool-calling-file {
    max-width: 120px;
  }
}

.reasoning-section {
  padding-top: 6px;
}

.reasoning-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--vscode-editorWarning-foreground, #b89500);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 0;
}

.reasoning-toggle:hover {
  color: var(--vscode-editorWarning-foreground, #d97706);
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
  background: rgba(217, 119, 6, 0.08);
  border: 1px solid rgba(217, 119, 6, 0.2);
  border-radius: 6px;
}

.reasoning-text {
  margin: 0;
  font-family: var(--vscode-editor-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 11px;
  color: var(--vscode-editorWarning-foreground, #b89500);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

/* ==================== 撤销按钮（底部右对齐） ==================== */
.undo-section {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

.undo-btn {
  background: rgba(245, 108, 108, 0.1);
  border: 1px solid rgba(245, 108, 108, 0.2);
  color: #ef4444;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.undo-btn:hover {
  background: rgba(245, 108, 108, 0.2);
}

/* ==================== Markdown 内容 ==================== */
:deep(.markdown-body) {
  word-wrap: break-word;
  overflow-wrap: break-word;
  color: var(--vscode-editor-foreground, #333333);
  font-size: 13px;
  line-height: 1.6;
}

:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3),
:deep(.markdown-body h4),
:deep(.markdown-body h5),
:deep(.markdown-body h6) {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.25;
}

:deep(.markdown-body h1) { font-size: 1.5em; border-bottom: 1px solid var(--vscode-widget-border, #e0e0e0); padding-bottom: 0.3em; }
:deep(.markdown-body h2) { font-size: 1.3em; border-bottom: 1px solid var(--vscode-widget-border, #e0e0e0); padding-bottom: 0.3em; }
:deep(.markdown-body h3) { font-size: 1.1em; }
:deep(.markdown-body p) { margin-bottom: 1em; }
:deep(.markdown-body ul),
:deep(.markdown-body ol) { padding-left: 2em; margin-bottom: 1em; }
:deep(.markdown-body li) { margin-bottom: 0.25em; }
:deep(.markdown-body blockquote) {
  margin: 1em 0;
  padding: 0.5em 1em;
  color: var(--vscode-descriptionForeground, #808080);
  border-left: 0.25em solid var(--vscode-widget-border, #e0e0e0);
  background: var(--vscode-sideBar-background, #f3f3f3);
  border-radius: 0 4px 4px 0;
}
:deep(.markdown-body code) {
  font-family: var(--vscode-editor-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}
:deep(.markdown-body pre) {
  background: var(--vscode-sideBar-background, #f3f3f3);
  border: 1px solid var(--vscode-widget-border, #e0e0e0);
  border-radius: 6px;
  padding: 1em;
  overflow: auto;
  margin: 1em 0;
}
:deep(.markdown-body pre code) {
  background-color: transparent;
  padding: 0;
  font-size: 0.8em;
  line-height: 1.45;
}
:deep(.markdown-body table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
}
:deep(.markdown-body table th),
:deep(.markdown-body table td) {
  border: 1px solid var(--vscode-widget-border, #e0e0e0);
  padding: 0.6em 1em;
}
:deep(.markdown-body table th) {
  font-weight: 600;
  background: var(--vscode-sideBar-background, #f3f3f3);
}
:deep(.markdown-body a) { color: var(--vscode-textLink-foreground, #006ab1); text-decoration: none; }
:deep(.markdown-body a:hover) { text-decoration: underline; }
:deep(.markdown-body img) { max-width: 100%; height: auto; }
:deep(.markdown-body hr) { height: 0.25em; padding: 0; margin: 1.5em 0; background-color: var(--vscode-widget-border, #e0e0e0); border: 0; }
:deep(.markdown-body strong) { font-weight: 600; }
:deep(.markdown-body em) { font-style: italic; }

/* ==================== 撤销确认弹窗 ==================== */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.confirm-dialog {
  background: var(--vscode-editor-background, #ffffff);
  border: 1px solid var(--vscode-widget-border, #e0e0e0);
  border-radius: 8px;
  padding: 20px;
  min-width: 280px;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.confirm-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--vscode-editor-foreground, #333333);
  margin-bottom: 8px;
}

.confirm-body {
  font-size: 13px;
  color: var(--vscode-editor-foreground, #333333);
  margin-bottom: 16px;
  line-height: 1.5;
}

.confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn {
  border: none;
  border-radius: 4px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}

.btn-secondary {
  background: var(--vscode-button-secondaryBackground, #e0e0e0);
  color: var(--vscode-button-secondaryForeground, #333333);
  border: 1px solid var(--vscode-button-border, transparent);
}

.btn-secondary:hover {
  background: var(--vscode-button-secondaryHoverBackground, #d0d0d0);
}

.btn-danger {
  background: #ef4444;
  color: #ffffff;
}

.btn-danger:hover {
  background: #dc2626;
}

/* ==================== Diff 弹窗 ==================== */
.diff-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.diff-dialog {
  background: var(--vscode-editor-background, #ffffff);
  border: 1px solid var(--vscode-widget-border, #e0e0e0);
  border-radius: 8px;
  width: 80%;
  height: 80%;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid var(--vscode-widget-border, #e0e0e0);
}

.diff-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--vscode-editor-foreground, #333);
}

.diff-close {
  background: none;
  border: none;
  font-size: 16px;
  cursor: pointer;
  color: var(--vscode-descriptionForeground, #808080);
  padding: 2px 6px;
  border-radius: 3px;
}

.diff-close:hover {
  background: var(--vscode-list-hoverBackground, #e8e8e8);
}

.diff-body {
  flex: 1;
  overflow: auto;
  padding: 0;
}

.diff-loading {
  text-align: center;
  padding: 40px;
  color: var(--vscode-descriptionForeground, #808080);
}

.diff-view {
  font-family: var(--vscode-editor-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 12px;
  line-height: 1.6;
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
  width: 72px;
  flex-shrink: 0;
  text-align: right;
  color: #555;
  padding-right: 12px;
  user-select: none;
}

.diff-line-content {
  white-space: pre;
  flex: 1;
}

.diff-line.add { background: #d4edda; }
.diff-line.del { background: #f8d7da; }
.diff-line.head { background: #f0f0f0; color: #1a1a1a; font-weight: 600; }
.diff-line.ctx { color: #1a1a1a; }

.diff-line.add .diff-line-content { color: #1a1a1a; font-weight: 500; }
.diff-line.del .diff-line-content { color: #1a1a1a; font-weight: 500; }
.diff-line.head .diff-line-content { color: #1a1a1a; font-weight: 600; }

/* ==================== 用户消息折叠 ==================== */
.user-msg-collapsed {
  max-height: 4.5em;
  overflow: hidden;
  position: relative;
}

.user-msg-collapsed::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2em;
  background: linear-gradient(transparent, var(--vscode-editor-background, #fff));
  pointer-events: none;
}
</style>
