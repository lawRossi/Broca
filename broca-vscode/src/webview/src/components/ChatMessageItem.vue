<script setup lang="ts">
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { diffLines } from 'diff'
import type { Message } from '../types'
import { useChatStore } from '../stores/chat'
import FilePreview from './FilePreview.vue'

const props = defineProps<{
  message: Message
}>()

const chatStore = useChatStore()

// Configure marked for safety
marked.setOptions({
  breaks: true,
  gfm: true,
})

// ==================== 展开状态 ====================
const showParameters = ref(false)
const showResult = ref(false)
const showReasoning = ref(false)

// ==================== 撤销按钮状态 ====================
const showActions = ref(false)
const showUndoConfirm = ref(false)

// ==================== 文件预览 ====================
const showFilePreview = ref(false)
const previewFilePath = ref('')
const previewFileUrl = ref('')

// ==================== 消息类型判断 ====================
const isUser = computed(() => props.message.message_type === 'user_message' || props.message.role === 'user')
const isSystem = computed(() => props.message.message_type === 'system_message' || props.message.role === 'system')
const isToolCall = computed(() => props.message.message_type === 'tool_call')
const isAgentResponse = computed(() => props.message.message_type === 'agent_response' || props.message.role === 'assistant')
const isError = computed(() => props.message.message_type === 'error' || props.message.message_type === 'agent_error')

// ==================== 特殊工具检测 ====================
const isEditFile = computed(() => isToolCall.value && props.message.data?.tool_name === 'edit_file')
const isWriteFile = computed(() => isToolCall.value && props.message.data?.tool_name === 'write_file')
const isReadFile = computed(() => isToolCall.value && props.message.data?.tool_name === 'read_file')
const isTodoManagement = computed(() => isToolCall.value && props.message.data?.tool_name === 'todo_management')
const isAskUser = computed(() => isToolCall.value && props.message.data?.tool_name === 'ask_user')

// ==================== 发送者信息 ====================
const senderName = computed(() => {
  if (isUser.value) {
    const targetAgentId = props.message.receiver_id || props.message.agent_id
    if (targetAgentId && targetAgentId !== chatStore.defaultAgentId) {
      const targetName = chatStore.agentNames[targetAgentId] || targetAgentId
      return `You → @${targetName}`
    }
    return 'You'
  }
  if (isError.value) return 'Error'
  if (isToolCall.value) {
    const senderAgentId = props.message.sender_id || props.message.agent_id
    if (senderAgentId && chatStore.agentNames[senderAgentId]) {
      return `@${chatStore.agentNames[senderAgentId]} - Tool`
    }
    return ''
  }
  if (isSystem.value) return 'System'
  const agentId = props.message.sender_id || props.message.agent_id
  if (agentId && chatStore.agentNames[agentId]) return `@${chatStore.agentNames[agentId]}`
  return agentId || 'Assistant'
})

// ==================== 消息图标 ====================
const messageIcon = computed(() => {
  if (isUser.value) return '👤'
  if (isError.value) return '⚠️'
  if (isToolCall.value) {
    const hasResult = props.message.data?.result !== undefined
    const status = props.message.data?.status
    if (!hasResult) return '🔧⏳'
    if (status === true || status === 'success') return '🔧✅'
    if (status === false || status === 'error') return '🔧❌'
    return '🔧'
  }
  if (isSystem.value) return '💬'
  return '🤖'
})

// ==================== 消息背景色 ====================
const bgClass = computed(() => {
  if (isUser.value) return 'message-user'
  if (isError.value) return 'message-error'
  if (isToolCall.value) return 'message-tool'
  if (isSystem.value) return 'message-system'
  return 'message-agent'
})

// ==================== 时间戳 ====================
const timestamp = computed(() => {
  const date = new Date(props.message.timestamp)
  return formatTime(date)
})

function formatTime(date: Date): string {
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  const isThisYear = date.getFullYear() === now.getFullYear()
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const ss = String(date.getSeconds()).padStart(2, '0')
  if (isToday) return `${hh}:${mm}:${ss}`
  if (isThisYear) return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${hh}:${mm}`
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${hh}:${mm}`
}

// ==================== 内容提取 ====================
function getContent(message: Message): string {
  if (message.message_type === 'tool_call') {
    return message.data?.tool_name || 'unknown_tool'
  }

  const content = message.data?.content || message.data?.message || ''

  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      if (parsed && typeof parsed === 'object' && parsed.content !== undefined) {
        if (Array.isArray(parsed.content)) {
          return parsed.content.filter((part: any) => part.type === 'text').map((part: any) => part.text).join('')
        }
        return parsed.content
      }
      return JSON.stringify(parsed, null, 2)
    } catch {
      return content
    }
  }
  return String(content)
}

// ==================== Agent Response 渲染 ====================
const agentResponseContent = computed(() => {
  if (!isAgentResponse.value || !props.message.data?.content) return ''
  try {
    const parsed = JSON.parse(props.message.data.content)
    return parsed.content || ''
  } catch {
    return props.message.data.content
  }
})

const renderedContent = computed(() => {
  const content = agentResponseContent.value
  if (!content) return ''
  try {
    return marked.parse(content) as string
  } catch {
    return content
  }
})

const agentReasoning = computed(() => {
  if (!isAgentResponse.value || !props.message.data?.content) return ''
  try {
    const parsed = JSON.parse(props.message.data.content)
    return parsed.reasoning_content || ''
  } catch {
    return ''
  }
})

// ==================== Tool Call 渲染 ====================
const toolName = computed(() => props.message.data?.name || props.message.data?.tool_name || 'Tool')
const toolArgs = computed(() => {
  try {
    const args = props.message.data?.arguments || props.message.data?.args || {}
    return typeof args === 'string' ? JSON.parse(args) : args
  } catch {
    return props.message.data?.arguments || {}
  }
})
const toolResult = computed(() => {
  const result = props.message.data?.result
  if (!result) return ''
  if (typeof result === 'string') return result
  return JSON.stringify(result, null, 2)
})

// ==================== edit_file Diff ====================
interface DiffLine {
  type: 'added' | 'removed' | 'unchanged'
  content: string
}

const editFileParams = computed(() => {
  if (!isEditFile.value) return null
  const args = toolArgs.value
  return {
    path: args.path || '',
    oldText: args.old_text || '',
    newText: args.new_text || '',
    encoding: args.encoding || 'utf-8',
    newFile: args.new_file || false,
  }
})

const computeDiff = (oldText: string, newText: string): DiffLine[] => {
  const result: DiffLine[] = []
  const diffResult = diffLines(oldText || '', newText || '')

  diffResult.forEach((part) => {
    const lines = part.value.split('\n')
    if (lines.length > 0 && lines[lines.length - 1] === '') {
      lines.pop()
    }
    lines.forEach((line) => {
      if (part.added) {
        result.push({ type: 'added', content: line })
      } else if (part.removed) {
        result.push({ type: 'removed', content: line })
      } else {
        result.push({ type: 'unchanged', content: line })
      }
    })
  })
  return result
}

// ==================== todo_management ====================
const todos = computed(() => {
  if (!isTodoManagement.value) return null
  const argsData = props.message.data?.arguments || props.message.data?.parameters
  if (!argsData) return null
  if (typeof argsData !== 'object') {
    try {
      return JSON.parse(argsData).todos || null
    } catch {
      return null
    }
  }
  return argsData.todos || null
})

// ==================== ask_user ====================
const askUserParams = computed(() => {
  if (!isAskUser.value) return null
  const args = props.message.data?.arguments || props.message.data?.parameters
  if (!args) return null
  return typeof args === 'string' ? JSON.parse(args) : args
})

const askUserResult = computed(() => {
  if (!isAskUser.value) return null
  return props.message.data?.result
})

// ==================== write_file ====================
const writeFileContent = computed(() => {
  if (!isWriteFile.value) return ''
  const args = toolArgs.value
  return args.content?.trim() || ''
})

// ==================== read_file ====================
const readFileResult = computed(() => {
  if (!isReadFile.value) return ''
  return toolResult.value
})

// ==================== JSON 格式化 ====================
const getFormattedJson = (data: any): string => {
  if (data === null || data === undefined) return 'null'
  try {
    if (typeof data === 'string') {
      try {
        const parsed = JSON.parse(data)
        return JSON.stringify(parsed, null, 2)
      } catch {
        return data
      }
    }
    if (typeof data === 'object' || Array.isArray(data)) {
      return JSON.stringify(data, null, 2)
    }
    return String(data)
  } catch {
    return String(data)
  }
}

// ==================== 文件附件 ====================
const files = computed(() => {
  return props.message.data?.files || []
})

const openFilePreview = (file: { url?: string; path?: string; name?: string; type?: string }) => {
  if (file.url) {
    previewFilePath.value = ''
    previewFileUrl.value = file.url
  } else if (file.path) {
    previewFileUrl.value = ''
    previewFilePath.value = file.path
  }
  showFilePreview.value = true
}

const getFileIcon = (fileType?: string, fileName?: string): string => {
  const type = fileType?.toLowerCase() || ''
  const name = fileName?.toLowerCase() || ''
  if (type.startsWith('image/') || /\.(jpg|jpeg|png|gif|bmp|svg|webp)$/.test(name)) return '🖼️'
  if (type.startsWith('video/') || /\.(mp4|mov|avi|wmv|flv|mkv)$/.test(name)) return '📹'
  if (type.startsWith('audio/') || /\.(mp3|wav|ogg|m4a)$/.test(name)) return '🎵'
  if (type.includes('pdf') || /\.pdf$/.test(name)) return '📄'
  if (type.includes('word') || /\.(doc|docx)$/.test(name)) return '📝'
  if (type.includes('excel') || /\.(xls|xlsx|csv)$/.test(name)) return '📊'
  if (type.includes('text/') || /\.(txt|md|json|xml|html|css|js|ts)$/.test(name)) return '📃'
  if (type.includes('zip') || /\.(zip|rar|7z|tar|gz)$/.test(name)) return '📦'
  return '📎'
}

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

// ==================== 撤销功能 ====================
const canUndo = computed(() => {
  if (!chatStore.connected || !chatStore.sessionId) return false
  const undoableTypes = ['user_message', 'tool_call', 'agent_response']
  return undoableTypes.includes(props.message.message_type)
})

const undoLevel = computed(() => {
  return props.message.message_type === 'user_message' ? 'turn' : 'step'
})

function handleUndo() {
  showUndoConfirm.value = true
}

function confirmUndo() {
  showUndoConfirm.value = false
  // 撤销需要指定目标 agent：
  // - 用户消息 (user_message): receiver_id 是目标 agent（消息发给了谁）
  // - Agent 消息 (agent_response/tool_call): agent_id 或 sender_id 是目标 agent
  const targetAgentId = isUser.value
    ? (props.message.receiver_id || chatStore.defaultAgentId)
    : (props.message.agent_id || props.message.sender_id || chatStore.defaultAgentId)
  chatStore.sendUndo(props.message.message_id, undoLevel.value, targetAgentId)
}

function cancelUndo() {
  showUndoConfirm.value = false
}

function toggleToolParams() {
  // todo_management 和 ask_user 始终展开，不响应点击切换
  if (!isTodoManagement.value && !isAskUser.value) {
    showParameters.value = !showParameters.value
  }
}
</script>

<template>
  <div
    class="message-item"
    :class="[bgClass]"
    @mouseenter="showActions = true"
    @mouseleave="showActions = false"
  >
    <!-- ==================== 消息头 ==================== -->
    <div v-if="!isSystem" class="message-header">
      <div class="header-left">
        <span class="message-icon">{{ messageIcon }}</span>
        <span class="sender-name">{{ senderName }}</span>
      </div>
      <div class="header-right">
        <span class="message-time">{{ timestamp }}</span>
        <!-- 撤销按钮 -->
        <div v-if="showActions && canUndo" class="hover-actions">
          <button class="undo-btn" @click.stop="handleUndo" title="撤销此操作">↩️ 撤销</button>
        </div>
      </div>
    </div>

    <!-- ==================== 系统消息 ==================== -->
    <div v-if="isSystem" class="system-content">
      {{ props.message.data?.content }}
    </div>

    <!-- ==================== 用户消息 ==================== -->
    <template v-else-if="isUser">
      <pre class="message-text">{{ getContent(props.message) }}</pre>
      <!-- 文件附件 -->
      <div v-if="files.length > 0" class="file-attachments">
        <div
          v-for="(file, index) in files"
          :key="index"
          class="file-attachment"
          @click="openFilePreview(file)"
        >
          <span class="file-icon">{{ getFileIcon(file.type, file.name) }}</span>
          <div class="file-info">
            <span class="file-name">{{ file.name }}</span>
            <span class="file-size">{{ formatFileSize(file.size) }}</span>
          </div>
          <span class="file-preview-icon">👁️</span>
        </div>
      </div>
    </template>

    <!-- ==================== Agent 响应 ==================== -->
    <template v-else-if="isAgentResponse">
      <!-- 推理内容 -->
      <div v-if="agentReasoning" class="reasoning-section">
        <div class="reasoning-header" @click="showReasoning = !showReasoning">
          <span>{{ showReasoning ? '▼' : '▶' }}</span>
          <span>🧠 思考</span>
        </div>
        <div v-if="showReasoning" class="reasoning-content">
          {{ agentReasoning }}
        </div>
      </div>
      <!-- Markdown 内容 -->
      <div class="message-content markdown-body" v-html="renderedContent"></div>
    </template>

    <!-- ==================== 工具调用 ==================== -->
    <template v-else-if="isToolCall">
      <!-- 工具名标题行：点击可切换参数显示（todo_management 和 ask_user 始终展开，忽略点击） -->
      <div class="tool-call-header" @click="toggleToolParams()">
        <span class="tool-icon">🔧</span>
        <span class="tool-name">{{ toolName }}</span>
        <span v-if="!isTodoManagement && !isAskUser" class="expand-icon">{{ showParameters ? '▼' : '▶' }}</span>
      </div>

      <!-- ===== 参数区域 ===== -->
      <!-- todo_management: 始终展开，不依赖 showParameters -->
      <div v-if="isTodoManagement && todos" class="tool-params">
        <div class="todo-list">
          <div v-for="(todo, i) in todos" :key="i" class="todo-item">
            <span class="todo-status">
              <span v-if="todo.status === 'completed'">✅</span>
              <span v-else-if="todo.status === 'in_progress'">⏳</span>
              <span v-else>⬜️</span>
            </span>
            <span class="todo-name">{{ todo.name }}</span>
          </div>
        </div>
      </div>

      <!-- ask_user: 始终展开，不依赖 showParameters -->
      <div v-else-if="isAskUser && askUserParams" class="tool-params">
        <div class="ask-user-box">
          <div class="params-label">问题:</div>
          <div class="ask-question">{{ askUserParams.question }}</div>
          <div v-if="askUserParams.options?.length" class="ask-options">
            <div v-for="(opt, i) in askUserParams.options" :key="i" class="ask-option">
              <span class="opt-bullet">•</span>
              <span class="opt-name">{{ opt.name }}</span>
              <span v-if="opt.description" class="opt-desc">- {{ opt.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- edit_file: Diff 展示（可切换） -->
      <div v-else-if="isEditFile && editFileParams" class="tool-params">
        <div class="diff-wrapper">
          <div class="diff-header">
            <span class="diff-path">📝 {{ editFileParams.path }}</span>
          </div>
          <div v-if="showParameters" class="diff-container">
            <div
              v-for="(line, i) in computeDiff(editFileParams.oldText, editFileParams.newText)"
              :key="i"
              class="diff-line"
              :class="{
                'diff-added': line.type === 'added',
                'diff-removed': line.type === 'removed',
                'diff-unchanged': line.type === 'unchanged',
              }"
            >{{ line.content }}</div>
          </div>
        </div>
      </div>

      <!-- write_file: 文件内容预览（路径始终可见，内容可切换） -->
      <div v-else-if="isWriteFile" class="tool-params">
        <div class="file-wrapper">
          <div class="file-header">
            <span class="file-path">📝 {{ toolArgs.path || 'unknown' }}</span>
          </div>
          <pre v-if="showParameters" class="file-content">{{ writeFileContent }}</pre>
        </div>
      </div>

      <!-- 其他工具: JSON 参数（可切换） -->
      <div v-else-if="showParameters && Object.keys(toolArgs).length > 0" class="tool-params">
        <pre class="json-display">{{ JSON.stringify(toolArgs, null, 2) }}</pre>
      </div>

      <!-- ===== 结果展示 ===== -->
      <!-- read_file: 可切换，标题为 "📊 文件内容" -->
      <div v-if="isReadFile && readFileResult" class="tool-result">
        <div class="result-header" @click="showResult = !showResult">
          <span>📊 文件内容</span>
          <span class="expand-icon">{{ showResult ? '▼' : '▶' }}</span>
        </div>
        <div v-if="showResult" class="result-content">
          <pre>{{ readFileResult }}</pre>
        </div>
      </div>
      <!-- ask_user 结果：始终展开，无切换按钮 -->
      <div v-else-if="isAskUser && askUserResult !== null" class="tool-result">
        <div class="result-label">回答:</div>
        <div class="result-content ask-result">
          <pre>{{ askUserResult }}</pre>
        </div>
      </div>
      <!-- 其他工具结果：可切换，排除 edit_file、write_file、todo_manage（它们的结果内联展示） -->
      <div v-else-if="toolResult && !isEditFile && !isWriteFile && !isTodoManagement" class="tool-result">
        <div class="result-header" @click="showResult = !showResult">
          <span>📊 结果</span>
          <span class="expand-icon">{{ showResult ? '▼' : '▶' }}</span>
        </div>
        <div v-if="showResult" class="result-content">
          <pre>{{ toolResult }}</pre>
        </div>
      </div>
    </template>

    <!-- ==================== 错误消息 ==================== -->
    <template v-else-if="isError">
      <pre class="message-text error-text">{{ props.message.data?.content || props.message.data?.message }}</pre>
    </template>

    <!-- ==================== 撤销确认弹窗 ==================== -->
    <Teleport to="body">
      <div v-if="showUndoConfirm" class="dialog-overlay" @click.self="cancelUndo">
        <div class="confirm-dialog">
          <div class="confirm-title">确认撤销</div>
          <div class="confirm-body">确定要撤销此操作吗？</div>
          <div class="confirm-footer">
            <button class="btn btn-secondary" @click="cancelUndo">取消</button>
            <button class="btn btn-danger" @click="confirmUndo">确定撤销</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ==================== 文件预览弹窗 ==================== -->
    <FilePreview
      :visible="showFilePreview"
      :file-path="previewFilePath"
      :file-url="previewFileUrl"
      @close="showFilePreview = false"
    />
  </div>
</template>

<style scoped>
/* ==================== 基础样式 ==================== */
.message-item {
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.5;
  position: relative;
  transition: all 0.2s ease;
}

.message-item:hover {
  filter: brightness(1.02);
}

/* ==================== 消息类型样式 ==================== */
.message-user {
  background: var(--message-user-bg, #eff6ff);
  border-left: 4px solid var(--message-user-border, #3b82f6);
  margin-left: 8px;
}

.message-agent {
  background: var(--message-agent-bg, #f0fdf4);
  border-left: 4px solid var(--message-agent-border, #22c55e);
  margin-right: 8px;
}

.message-tool {
  background: var(--message-tool-bg, #faf5ff);
  border-left: 4px solid var(--message-tool-border, #a855f7);
  font-size: 12px;
}

.message-system {
  text-align: center;
  background: var(--message-system-bg, #f3f4f6);
  border: 1px solid var(--border-color);
}

.message-error {
  background: var(--message-error-bg, #fef2f2);
  border-left: 4px solid var(--message-error-border, #ef4444);
  color: var(--error-fg);
}

/* ==================== 消息头 ==================== */
.message-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.message-icon {
  font-size: 16px;
  line-height: 1;
}

.sender-name {
  font-weight: 600;
  font-size: 12px;
  color: var(--text-link);
}

.message-time {
  font-size: 11px;
  color: var(--text-secondary);
}

/* ==================== 悬停操作 ==================== */
.hover-actions {
  opacity: 0;
  transition: opacity 0.2s ease;
}

.message-item:hover .hover-actions {
  opacity: 1;
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

/* ==================== 消息内容 ==================== */
.message-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: inherit;
  color: var(--text-primary);
}

.system-content {
  color: var(--text-secondary);
  font-style: italic;
  font-size: 12px;
  padding: 4px 0;
}

.error-text {
  color: var(--error-fg);
}

/* ==================== 推理内容 ==================== */
.reasoning-section {
  margin-bottom: 8px;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 0;
  font-size: 12px;
  color: var(--warning-fg);
}

.reasoning-content {
  padding: 8px 12px;
  background: var(--reasoning-bg, #fffbeb);
  border-left: 3px solid var(--warning-fg);
  border-radius: 4px;
  font-size: 12px;
  color: var(--reasoning-text, #92400e);
  font-style: italic;
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 4px;
}

/* ==================== 工具调用 ==================== */
.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 0;
}

.tool-icon {
  font-size: 14px;
}

.tool-name {
  font-weight: 500;
  color: var(--warning-fg);
}

.expand-icon {
  font-size: 10px;
  color: var(--text-secondary);
}

.tool-params {
  margin-top: 4px;
}

.tool-result {
  margin-top: 4px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  margin-top: 4px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--success-fg);
}

.result-content {
  padding: 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  overflow-x: auto;
  margin-top: 4px;
}

.result-content pre {
  margin: 0;
  font-family: var(--code-font-family);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-primary);
}

/* ==================== Diff 展示 ==================== */
.diff-wrapper,
.file-wrapper {
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
  background: var(--bg-primary);
}

.diff-header,
.file-header {
  padding: 6px 10px;
  background: rgba(168, 85, 247, 0.1);
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
}

.diff-path,
.file-path {
  color: var(--text-link);
  font-weight: 500;
}

.diff-container {
  max-height: 400px;
  overflow-y: auto;
  overflow-x: auto;
}

.diff-line {
  display: block;
  white-space: pre;
  padding: 1px 0 1px 32px;
  position: relative;
  min-height: 22px;
  line-height: 22px;
  width: fit-content;
  min-width: 100%;
  font-family: var(--code-font-family);
  font-size: 11px;
}

.diff-line::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 28px;
  text-align: center;
  font-weight: 700;
  line-height: 22px;
}

.diff-added {
  background-color: #dcfce7;
  color: #166534;
}

.diff-added::before {
  content: '+';
  color: #16a34a;
}

.diff-removed {
  background-color: #fee2e2;
  color: #991b1b;
}

.diff-removed::before {
  content: '-';
  color: #dc2626;
}

.diff-unchanged {
  background-color: transparent;
  color: var(--text-primary);
}

.diff-unchanged::before {
  content: '';
}

.diff-line:hover {
  filter: brightness(0.95);
}

.diff-added:hover {
  background-color: #d4edda;
}

.diff-removed:hover {
  background-color: #f8d7da;
}

/* ==================== Todo 列表 ==================== */
.todo-list {
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-secondary);
}

.todo-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
}

.todo-status {
  font-size: 14px;
  line-height: 1.5;
}

.todo-name {
  font-size: 13px;
  color: var(--text-primary);
}

/* ==================== Ask User ==================== */
.params-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--warning-fg);
  margin-bottom: 4px;
}

.result-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--success-fg);
  margin-bottom: 4px;
}

.ask-user-box {
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-secondary);
}

.ask-question {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.ask-options {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ask-option {
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.opt-bullet {
  color: var(--warning-fg);
}

.opt-name {
  font-weight: 500;
  color: var(--text-primary);
}

.opt-desc {
  color: var(--text-secondary);
}

/* ==================== 文件内容 ==================== */
.file-content {
  margin: 0;
  padding: 10px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-family: var(--code-font-family);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
  color: var(--text-primary);
}

/* ==================== JSON 展示 ==================== */
.json-display {
  margin: 0;
  padding: 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-family: var(--code-font-family);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-x: auto;
  color: var(--text-primary);
}

/* ==================== 文件附件 ==================== */
.file-attachments {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.file-attachment {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  flex: 1;
  min-width: 0;
}

.file-attachment:hover {
  background: var(--input-bg);
  border-color: var(--focus-border);
}

.file-icon {
  font-size: 20px;
}

.file-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.file-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 10px;
  color: var(--text-secondary);
}

.file-preview-icon {
  font-size: 14px;
  color: var(--text-secondary);
}

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
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
  min-width: 280px;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.confirm-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.confirm-body {
  font-size: 13px;
  color: var(--text-primary);
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
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-secondary:hover {
  background: var(--border-color);
}

.btn-danger {
  background: #ef4444;
  color: #ffffff;
}

.btn-danger:hover {
  background: #dc2626;
}

/* ==================== Markdown 内容 ==================== */
:deep(.markdown-body) {
  word-wrap: break-word;
  overflow-wrap: break-word;
  color: var(--text-primary);
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

:deep(.markdown-body h1) { font-size: 1.5em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.3em; }
:deep(.markdown-body h2) { font-size: 1.3em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.3em; }
:deep(.markdown-body h3) { font-size: 1.1em; }
:deep(.markdown-body p) { margin-bottom: 1em; line-height: 1.6; }
:deep(.markdown-body ul),
:deep(.markdown-body ol) { padding-left: 2em; margin-bottom: 1em; }
:deep(.markdown-body li) { margin-bottom: 0.25em; }
:deep(.markdown-body blockquote) {
  margin: 1em 0;
  padding: 0.5em 1em;
  color: var(--text-secondary);
  border-left: 0.25em solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: 0 4px 4px 0;
}
:deep(.markdown-body code) {
  font-family: var(--code-font-family);
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}
:deep(.markdown-body pre) {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
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
  border: 1px solid var(--border-color);
  padding: 0.6em 1em;
}
:deep(.markdown-body table th) {
  font-weight: 600;
  background: var(--bg-tertiary);
}
:deep(.markdown-body a) { color: var(--text-link); text-decoration: none; }
:deep(.markdown-body a:hover) { text-decoration: underline; }
:deep(.markdown-body img) { max-width: 100%; height: auto; }
:deep(.markdown-body hr) { height: 0.25em; padding: 0; margin: 1.5em 0; background-color: var(--border-color); border: 0; }
:deep(.markdown-body strong) { font-weight: 600; }
:deep(.markdown-body em) { font-style: italic; }

/* ==================== 暗色模式 ==================== */
@media (prefers-color-scheme: dark) {
  .message-user {
    background: rgba(59, 130, 246, 0.1);
    border-left-color: #3b82f6;
  }
  .message-agent {
    background: rgba(34, 197, 94, 0.1);
    border-left-color: #22c55e;
  }
  .message-tool {
    background: rgba(168, 85, 247, 0.1);
    border-left-color: #a855f7;
  }
  .message-system {
    background: rgba(255, 255, 255, 0.05);
  }
  .message-error {
    background: rgba(239, 68, 68, 0.1);
    border-left-color: #ef4444;
  }
  .reasoning-content {
    background: rgba(217, 119, 6, 0.1);
    color: #fbbf24;
  }
  .diff-added {
    background-color: #064e3b;
    color: #a7f3d0;
  }
  .diff-added::before {
    color: #4ade80;
  }
  .diff-removed {
    background-color: #7f1d1d;
    color: #fecaca;
  }
  .diff-removed::before {
    color: #f87171;
  }
  .diff-unchanged {
    background-color: transparent;
    color: var(--text-primary);
  }
  .diff-added:hover {
    background-color: #065f46;
  }
  .diff-removed:hover {
    background-color: #991b1b;
  }
}
</style>
