<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage, onMessage } from '../api/vscode'
import { uploadFile } from '../utils/upload'

const chatStore = useChatStore()
const inputRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const mentionListRef = ref<HTMLElement>()

// ==================== @mention 智能提示 ====================
const showMentionSuggestions = ref(false)
const mentionSuggestions = ref<Array<{ id: string; name: string }>>([])
const mentionSearch = ref('')
const selectedMentionIndex = ref(-1)
const justSelectedMention = ref(false)

// ==================== /command 智能提示 ====================
interface CommandInfo {
  name: string
  description: string
  type: string
  argument_hint: string
}

const allCommands = ref<CommandInfo[]>([])

// Fallback commands when backend is not available
const fallbackCommands: CommandInfo[] = [
  { name: 'help', description: 'Show available commands', type: 'local', argument_hint: '[command_name]' },
  { name: 'abort', description: 'Abort current operation', type: 'local', argument_hint: '' },
  { name: 'undo', description: 'Undo last change', type: 'local', argument_hint: '' },
  { name: 'redo', description: 'Redo last undone change', type: 'local', argument_hint: '' },
  { name: 'ask', description: 'Answer questions only, no modifications', type: 'prompt', argument_hint: '<your question>' },
  { name: 'init', description: 'Initialize project and generate summary', type: 'prompt', argument_hint: '' },
  { name: 'plan', description: 'Create a plan document without executing', type: 'prompt', argument_hint: '<your goal>' },
  { name: 'execute-plan', description: 'Execute a plan document', type: 'prompt', argument_hint: '' },
]

// Fetch commands from the backend via extension host
function fetchCommands() {
  postMessage({ type: 'fetchCommands' })
  // Fallback timeout: use static list if backend doesn't respond within 3s
  setTimeout(() => {
    if (allCommands.value.length === 0) {
      allCommands.value = fallbackCommands
    }
  }, 3000)
}

// Listen for commands response
onMessage((data: any) => {
  if (data.type === 'commands') {
    const cmds = data.payload.commands || data.payload || []
    allCommands.value = Array.isArray(cmds) ? cmds : fallbackCommands
  }
})

const showCommandSuggestions = ref(false)
const commandSuggestions = ref<CommandInfo[]>([])
const commandSearch = ref('')
const selectedCommandIndex = ref(-1)
const commandSuggestionsRef = ref<HTMLElement>()
const justSelectedCommand = ref(false)

// 监听输入变化，检测 @mention 和 /command
watch(
  () => chatStore.inputText,
  (newValue) => {
    if (justSelectedMention.value || justSelectedCommand.value) return

    // ---- 检测 /command ----
    const slashIndex = newValue.lastIndexOf('/')
    if (slashIndex !== -1 && (slashIndex === 0 || newValue[slashIndex - 1] === ' ')) {
      const afterSlash = newValue.substring(slashIndex + 1)
      const spaceIndex = afterSlash.indexOf(' ')

      if (spaceIndex === -1) {
        // /后面还没有空格
        if (afterSlash.length > 0) {
          const searchTerm = afterSlash
          commandSearch.value = searchTerm
          commandSuggestions.value = allCommands.value.filter(
            (cmd) => cmd.name.toLowerCase().startsWith(searchTerm.toLowerCase())
          )
          if (commandSuggestions.value.length > 0) {
            showMentionSuggestions.value = false
            showCommandSuggestions.value = true
            selectedCommandIndex.value = 0
          } else {
            showCommandSuggestions.value = false
          }
        } else {
          // 只输入了 /，显示所有命令
          commandSearch.value = ''
          commandSuggestions.value = allCommands.value
          if (commandSuggestions.value.length > 0) {
            showMentionSuggestions.value = false
            showCommandSuggestions.value = true
            selectedCommandIndex.value = 0
          } else {
            showCommandSuggestions.value = false
          }
        }
        return // /command 优先，跳过 @mention
      } else if (spaceIndex > 0) {
        // /后面有内容后有空格，检查精确匹配
        const searchTerm = afterSlash.substring(0, spaceIndex)
        const isExactMatch = allCommands.value.some(
          (cmd) => cmd.name.toLowerCase() === searchTerm.toLowerCase()
        )
        if (isExactMatch) {
          showCommandSuggestions.value = false
        } else {
          showCommandSuggestions.value = false
        }
      } else {
        showCommandSuggestions.value = false
      }
    } else {
      showCommandSuggestions.value = false
    }

    // ---- 检测 @mention ----
    const lastAt = newValue.lastIndexOf('@')
    if (lastAt !== -1) {
      const afterAt = newValue.substring(lastAt + 1)
      const spaceIndex = afterAt.indexOf(' ')

      if (spaceIndex === -1 || spaceIndex > 0) {
        const searchTerm = spaceIndex === -1 ? afterAt : afterAt.substring(0, spaceIndex)
        mentionSearch.value = searchTerm

        // 如果@后面有空格且搜索词已精确匹配某个agent，说明mention已完成，不再显示建议
        if (spaceIndex !== -1) {
          const isExactMatch = Object.entries(chatStore.agentNames).some(
            ([id, name]) =>
              name.toLowerCase() === searchTerm.toLowerCase() ||
              id.toLowerCase() === searchTerm.toLowerCase()
          )
          if (isExactMatch) {
            showMentionSuggestions.value = false
            return
          }
        }

        // Filter agents
        const agentEntries = Object.entries(chatStore.agentNames)
        mentionSuggestions.value = agentEntries
          .filter(([id, name]) =>
            name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            id.toLowerCase().includes(searchTerm.toLowerCase())
          )
          .map(([id, name]) => ({ id, name }))

        if (mentionSuggestions.value.length > 0) {
          showMentionSuggestions.value = true
          selectedMentionIndex.value = 0
        } else {
          showMentionSuggestions.value = false
        }
      } else {
        showMentionSuggestions.value = false
      }
    } else {
      showMentionSuggestions.value = false
    }
  }
)

function selectMention(agentId: string, agentName: string) {
  const input = chatStore.inputText
  const lastAt = input.lastIndexOf('@')
  if (lastAt !== -1) {
    const beforeAt = input.substring(0, lastAt)
    const afterAt = input.substring(lastAt)
    const spaceIndex = afterAt.indexOf(' ')

    let replacement = ''
    if (spaceIndex === -1) {
      replacement = `${beforeAt}@${agentName} `
    } else {
      replacement = `${beforeAt}@${agentName}${afterAt.substring(spaceIndex)}`
    }

    justSelectedMention.value = true
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1
    chatStore.inputText = replacement

    setTimeout(() => {
      justSelectedMention.value = false
    }, 100)
  } else {
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1
  }
}

function selectCommand(commandName: string) {
  const input = chatStore.inputText
  const slashIndex = input.lastIndexOf('/')
  if (slashIndex !== -1) {
    const beforeSlash = input.substring(0, slashIndex)
    const afterSlash = input.substring(slashIndex)
    const spaceIndex = afterSlash.indexOf(' ')

    let replacement = ''
    if (spaceIndex === -1) {
      replacement = `${beforeSlash}/${commandName} `
    } else {
      replacement = `${beforeSlash}/${commandName}${afterSlash.substring(spaceIndex)}`
    }

    justSelectedCommand.value = true
    showCommandSuggestions.value = false
    commandSearch.value = ''
    selectedCommandIndex.value = -1
    chatStore.inputText = replacement

    setTimeout(() => {
      justSelectedCommand.value = false
    }, 100)
  } else {
    showCommandSuggestions.value = false
    commandSearch.value = ''
    selectedCommandIndex.value = -1
  }
}

function handleCommandClick(event: MouseEvent, commandName: string) {
  event.stopPropagation()
  selectCommand(commandName)
}

function handleMentionClick(event: MouseEvent, agentId: string, agentName: string) {
  event.stopPropagation()
  selectMention(agentId, agentName)
}

// 点击外部关闭 mention/command 列表
function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  const mentionList = mentionListRef.value
  const cmdList = commandSuggestionsRef.value

  // 关闭 command 列表
  if (showCommandSuggestions.value && cmdList && !cmdList.contains(target)) {
    showCommandSuggestions.value = false
    commandSearch.value = ''
    selectedCommandIndex.value = -1
  }

  // 关闭 mention 列表
  if (showMentionSuggestions.value && mentionList && !mentionList.contains(target)) {
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)

  // Fetch available commands for autocomplete
  fetchCommands()

  // 监听文件上传错误（统一 upload 模块不再需要监听 fileUploaded，通过 Promise 处理）
  onMessage((data: any) => {
    if (data.type === 'error') {
      // 将所有上传中的文件标记为失败
      for (const record of pendingFiles.value) {
        if (record.status === 'uploading') {
          record.status = 'error'
          record.error = data.payload?.message || 'Upload failed'
          uploadingFileIds.value.delete(record.id)
        }
      }
      isUploading.value = false
    }
  })
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

const pendingFiles = ref<Array<{
  file: File
  id: string
  status: 'pending' | 'uploading' | 'success' | 'error'
  progress: number
  error?: string
  uploadedData?: {
    name: string
    url: string
    path: string
    size: number
    type: string
  }
}>>([])

const isUploading = ref(false)

// 用于追踪正在上传的文件记录
const uploadingFileIds = ref<Set<string>>(new Set())

const canSend = computed(() => {
  const text = chatStore.inputText.trim()
  return text.length > 0 || pendingFiles.value.some(f => f.status === 'success')
})

function triggerFileSelect() {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  if (!target.files) return

  const files = Array.from(target.files)
  for (const file of files) {
    const id = Math.random().toString(36).substr(2, 9)
    pendingFiles.value.push({ file, id, status: 'pending', progress: 0 })
  }

  target.value = ''
  await uploadPendingFiles()
}

function removePendingFile(id: string) {
  const idx = pendingFiles.value.findIndex(f => f.id === id)
  if (idx !== -1) {
    const record = pendingFiles.value[idx]
    if (record && record.status !== 'uploading') {
      pendingFiles.value.splice(idx, 1)
    }
  }
}

async function uploadPendingFiles() {
  isUploading.value = true
  for (const record of pendingFiles.value) {
    if (record.status !== 'pending') continue

    record.status = 'uploading'
    record.progress = 0
    uploadingFileIds.value.add(record.id)

    try {
      // 使用统一的 uploadFile 模块上传（通过 postMessage 转发到扩展进程）
      const result = await uploadFile(record.file)
      record.uploadedData = result
      record.status = 'success'
      record.progress = 100
      uploadingFileIds.value.delete(record.id)
    } catch (error: any) {
      record.status = 'error'
      record.error = error.message || '读取文件失败'
      uploadingFileIds.value.delete(record.id)
    }
  }
  isUploading.value = false
}

// ==================== 发送消息 ====================
function handleSend() {
  // 如果刚选择了命令或mention，跳过发送
  if (justSelectedCommand.value || justSelectedMention.value) {
    return
  }

  const text = chatStore.inputText.trim()
  console.log('[ChatInput] handleSend called, text:', JSON.stringify(text), 'runnerAlive:', chatStore.runnerAlive)

  // 检测 /redo 命令
  if (text === '/redo') {
    chatStore.inputText = ''
    chatStore.sendRedo()
    return
  }

  const uploadedFiles = pendingFiles.value
    .filter(f => f.status === 'success' && f.uploadedData)
    .map(f => ({
      name: f.uploadedData!.name,
      url: f.uploadedData!.url,
      path: f.uploadedData!.path,
      size: f.uploadedData!.size,
      type: f.uploadedData!.type,
      upload_time: new Date().toISOString(),
    }))

  if (!text && uploadedFiles.length === 0) return

  // Parse @mention — 将 @名称 解析为实际的 agent_id
  let cleanText = text
  let targetAgentId: string | undefined

  const mentionMatch = text.match(/@([\w-]+)/)
  if (mentionMatch) {
    const mentionName = mentionMatch[1].toLowerCase()
    cleanText = text.replace(/@[\w-]+\s*/, '').trim()

    // 反向查找：从 agentNames (agent_id → name) 中找到匹配的 agent_id
    const matchedEntry = Object.entries(chatStore.agentNames).find(([id, name]) =>
      name.toLowerCase() === mentionName || id.toLowerCase() === mentionName
    )
    if (matchedEntry) {
      targetAgentId = matchedEntry[0]  // 使用真实的 agent_id
    } else {
      // 如果没找到匹配的 agent，就用原始文本（兼容直接输入 agent_id 的情况）
      targetAgentId = mentionMatch[1]
    }
  }

  console.log('[ChatInput] Sending:', { cleanText, targetAgentId, uploadedFiles: uploadedFiles.length })
  chatStore.sendMessage(cleanText, targetAgentId, uploadedFiles)
  chatStore.inputText = ''

  // Clear uploaded files
  pendingFiles.value = pendingFiles.value.filter(f => f.status !== 'success')

  // Re-focus input
  inputRef.value?.focus()
}

function handleKeydown(event: KeyboardEvent) {
  // /command 列表导航（优先于 @mention）
  if (showCommandSuggestions.value && commandSuggestions.value.length > 0) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        selectedCommandIndex.value = Math.min(selectedCommandIndex.value + 1, commandSuggestions.value.length - 1)
        return
      case 'ArrowUp':
        event.preventDefault()
        selectedCommandIndex.value = Math.max(selectedCommandIndex.value - 1, 0)
        return
      case 'Enter':
        if (selectedCommandIndex.value >= 0 && selectedCommandIndex.value < commandSuggestions.value.length) {
          event.preventDefault()
          const suggestion = commandSuggestions.value[selectedCommandIndex.value]
          if (suggestion) {
            selectCommand(suggestion.name)
          }
          return
        }
        break
      case 'Escape':
        showCommandSuggestions.value = false
        commandSearch.value = ''
        selectedCommandIndex.value = -1
        return
    }
  }

  // @mention 列表导航
  if (showMentionSuggestions.value) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        selectedMentionIndex.value = Math.min(selectedMentionIndex.value + 1, mentionSuggestions.value.length - 1)
        return
      case 'ArrowUp':
        event.preventDefault()
        selectedMentionIndex.value = Math.max(selectedMentionIndex.value - 1, 0)
        return
      case 'Enter':
        if (selectedMentionIndex.value >= 0 && selectedMentionIndex.value < mentionSuggestions.value.length) {
          event.preventDefault()
          const suggestion = mentionSuggestions.value[selectedMentionIndex.value]
          if (suggestion) {
            selectMention(suggestion.id, suggestion.name)
          }
          return
        }
        break
      case 'Escape':
        showMentionSuggestions.value = false
        mentionSearch.value = ''
        selectedMentionIndex.value = -1
        return
    }
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}

// ==================== 工具函数 ====================
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function getFileIcon(file: File): string {
  if (file.type.startsWith('image/')) return '🖼️'
  if (file.type.startsWith('video/')) return '📹'
  if (file.type.includes('pdf')) return '📄'
  if (file.type.includes('text')) return '📃'
  return '📦'
}

// 当前目标 agent
const targetAgentDisplay = computed(() => {
  const text = chatStore.inputText
  const mentionMatch = text.match(/@([\w-]+)/)
  if (mentionMatch) {
    const mentionName = mentionMatch[1].toLowerCase()
    const agentEntry = Object.entries(chatStore.agentNames).find(([id, name]) =>
      name.toLowerCase() === mentionName || id.toLowerCase() === mentionName
    )
    return agentEntry ? agentEntry[1] : mentionMatch[1]
  }
  const defaultName = chatStore.defaultAgentId ? chatStore.agentNames[chatStore.defaultAgentId] : undefined
  return defaultName || chatStore.defaultAgentId || 'Assistant'
})
</script>

<template>
  <div class="input-container">
    <!-- 目标 Agent 提示 -->
    <div class="target-agent-hint" v-if="chatStore.runnerAlive">
      发送给: <span class="target-agent-name">@{{ targetAgentDisplay }}</span>
    </div>

    <!-- File preview area -->
    <div v-if="pendingFiles.length > 0" class="file-preview-area">
      <div
        v-for="record in pendingFiles"
        :key="record.id"
        class="file-item"
        :class="{
          'file-error': record.status === 'error',
          'file-success': record.status === 'success',
          'file-uploading': record.status === 'uploading',
        }"
      >
        <span>{{ getFileIcon(record.file) }}</span>
        <span class="file-name">{{ record.file.name }}</span>
        <span class="file-size">{{ formatFileSize(record.file.size) }}</span>
        <span v-if="record.status === 'uploading'" class="upload-status">上传中...</span>
        <span v-if="record.status === 'error'" class="upload-status error">{{ record.error }}</span>
        <div v-if="record.status === 'uploading'" class="progress-bar">
          <div class="progress-fill" :style="{ width: record.progress + '%' }"></div>
        </div>
        <button
          v-if="record.status !== 'uploading'"
          class="file-remove"
          @click="removePendingFile(record.id)"
        >✕</button>
      </div>
    </div>

    <!-- Input row -->
    <div class="input-row">
      <div class="input-wrapper">
        <textarea
          ref="inputRef"
          v-model="chatStore.inputText"
          class="chat-input"
          :placeholder="chatStore.runnerAlive ? '输入/执行命令，@指定agent' : '进程未运行，无法发送消息'"
          rows="1"
          @keydown="handleKeydown"
          :disabled="!chatStore.runnerAlive"
        ></textarea>

        <!-- /command 建议列表 -->
        <div
          v-if="showCommandSuggestions && commandSuggestions.length > 0"
          ref="commandSuggestionsRef"
          class="command-suggestions"
        >
          <div
            v-for="(suggestion, index) in commandSuggestions"
            :key="suggestion.name"
            class="command-item"
            :class="{ 'command-selected': index === selectedCommandIndex }"
            @click="handleCommandClick($event, suggestion.name)"
          >
            <span class="command-prefix">/</span>
            <div class="command-info">
              <span class="command-name">{{ suggestion.name }}</span>
              <span class="command-desc">{{ suggestion.description }}</span>
            </div>
            <span
              class="command-type"
              :class="suggestion.type === 'local' ? 'type-local' : 'type-prompt'"
            >{{ suggestion.type }}</span>
          </div>
        </div>

        <!-- @mention 建议列表 -->
        <div
          v-if="showMentionSuggestions && mentionSuggestions.length > 0"
          ref="mentionListRef"
          class="mention-suggestions"
        >
          <div
            v-for="(suggestion, index) in mentionSuggestions"
            :key="suggestion.id"
            class="mention-item"
            :class="{ 'mention-selected': index === selectedMentionIndex }"
            @click="handleMentionClick($event, suggestion.id, suggestion.name)"
          >
            <span class="mention-prefix">@</span>
            <span class="mention-name">{{ suggestion.name }}</span>
          </div>
        </div>
      </div>

      <button
        class="tool-button"
        title="Attach file"
        :disabled="!chatStore.runnerAlive"
        @click="triggerFileSelect"
      >
        📎
      </button>
      <input
        ref="fileInputRef"
        type="file"
        multiple
        class="hidden"
        @change="handleFileChange"
      />

      <button
        class="send-button"
        :disabled="!canSend || !chatStore.runnerAlive"
        @click="handleSend"
      >
        Send
      </button>
    </div>

  </div>
</template>

<style scoped>
.input-container {
  border-top: 1px solid var(--border-color);
  padding: 8px 12px;
  background: var(--bg-primary);
  position: relative;
}

/* ==================== 目标 Agent 提示 ==================== */
.target-agent-hint {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  padding: 0 2px;
}

.target-agent-name {
  font-weight: 600;
  color: var(--text-link);
}

/* ==================== 文件预览 ==================== */
.file-preview-area {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  max-height: 120px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 11px;
  min-width: 0;
  position: relative;
}

.file-item.file-error {
  border: 1px solid var(--error-fg);
}

.file-item.file-success {
  border: 1px solid var(--success-fg);
}

.file-item.file-uploading {
  border: 1px solid var(--focus-border);
}

.file-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  color: var(--text-secondary);
}

.upload-status {
  font-size: 10px;
  color: var(--text-secondary);
}

.upload-status.error {
  color: var(--error-fg);
}

.progress-bar {
  width: 50px;
  height: 4px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--button-bg);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.file-remove {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0 2px;
  font-size: 11px;
}

.file-remove:hover {
  color: var(--error-fg);
}

/* ==================== 输入区域 ==================== */
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.input-wrapper {
  flex: 1;
  position: relative;
}

.chat-input {
  width: 100%;
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 8px 12px;
  font-family: var(--font-family);
  font-size: var(--font-size);
  resize: none;
  outline: none;
  min-height: 36px;
  max-height: 120px;
}

.chat-input:focus {
  border-color: var(--focus-border);
}

.chat-input::placeholder {
  color: var(--text-secondary);
}

/* ==================== /command 建议列表 ==================== */
.command-suggestions {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 4px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.2);
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
}

.command-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 1px solid var(--border-color);
}

.command-item:last-child {
  border-bottom: none;
}

.command-item:hover,
.command-selected {
  background: var(--bg-tertiary);
}

.command-prefix {
  color: var(--button-bg);
  font-weight: 700;
  font-family: monospace;
  font-size: 15px;
  flex-shrink: 0;
}

.command-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.command-name {
  color: var(--text-primary);
  font-weight: 600;
  font-family: monospace;
}

.command-desc {
  color: var(--text-secondary);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.command-type {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  font-weight: 500;
}

.type-local {
  background: rgba(59, 130, 246, 0.15);
  color: var(--text-link);
}

.type-prompt {
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
}

/* ==================== @mention 建议列表 ==================== */
.mention-suggestions {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 4px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.2);
  max-height: 180px;
  overflow-y: auto;
  z-index: 100;
}

.mention-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 1px solid var(--border-color);
}

.mention-item:last-child {
  border-bottom: none;
}

.mention-item:hover,
.mention-selected {
  background: var(--bg-tertiary);
}

.mention-prefix {
  color: var(--text-link);
  font-weight: 600;
}

.mention-name {
  color: var(--text-primary);
  font-weight: 500;
}

/* ==================== 按钮 ==================== */
.tool-button {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}

.tool-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-button {
  background: var(--button-bg);
  color: var(--button-text);
  border: none;
  border-radius: 4px;
  padding: 8px 16px;
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
}

.send-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-button:hover:not(:disabled) {
  background: var(--button-hover-bg);
}

.hidden {
  display: none;
}

.disabled-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: not-allowed;
}
</style>
