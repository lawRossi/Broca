<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage, onMessage } from '../api/vscode'

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

// 监听输入变化，检测 @mention
watch(
  () => chatStore.inputText,
  (newValue) => {
    if (justSelectedMention.value) return

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

function handleMentionClick(event: MouseEvent, agentId: string, agentName: string) {
  event.stopPropagation()
  selectMention(agentId, agentName)
}

// 点击外部关闭 mention 列表
function handleClickOutside(event: MouseEvent) {
  if (!showMentionSuggestions.value) return
  const target = event.target as HTMLElement
  const mentionList = mentionListRef.value
  if (mentionList && !mentionList.contains(target)) {
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)

  // 监听文件上传结果
  onMessage((data: any) => {
    if (data.type === 'fileUploaded') {
      const { name, url, path: filePath, size, type } = data.payload
      // 找到匹配的 pending file record（通过文件名匹配）
      const record = pendingFiles.value.find(
        f => f.status === 'uploading' && f.file.name === name && f.file.size === size
      )
      if (record) {
        record.uploadedData = { name, url, path: filePath, size, type }
        record.status = 'success'
        record.progress = 100
        uploadingFileIds.value.delete(record.id)
        // 检查是否所有文件都已上传完成
        if (uploadingFileIds.value.size === 0) {
          isUploading.value = false
        }
      }
    } else if (data.type === 'error') {
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
      // 读取文件为 base64
      const base64 = await fileToBase64(record.file)

      // 通过扩展代理上传（扩展有 Supabase 客户端和 userId）
      postMessage({
        type: 'uploadFile',
        payload: {
          fileName: record.file.name,
          fileType: record.file.type,
          base64Data: base64,
          fileSize: record.file.size,
        },
      })
    } catch (error: any) {
      record.status = 'error'
      record.error = error.message || '读取文件失败'
      uploadingFileIds.value.delete(record.id)
    }
  }
  // 注意：不能在这里设 isUploading = false，因为上传是异步的
  // 需要在收到 fileUploaded 或 error 响应后设置
}

// 将 File 读取为 base64 字符串
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      // 去掉 data:xxx;base64, 前缀
      const result = reader.result as string
      const base64 = result.split(',')[1] || result
      resolve(base64)
    }
    reader.onerror = () => reject(new Error('Failed to read file'))
    reader.readAsDataURL(file)
  })
}

// ==================== 发送消息 ====================
function handleSend() {
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
          placeholder="Type a message... (use @ to mention an agent)"
          rows="1"
          @keydown="handleKeydown"
          :disabled="!chatStore.runnerAlive"
        ></textarea>

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
