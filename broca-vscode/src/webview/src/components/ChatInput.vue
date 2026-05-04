<script setup lang="ts">
import { ref, computed } from 'vue'
import { useChatStore } from '../stores/chat'
import { createClient } from '@supabase/supabase-js'
import { getInitialData } from '../api/vscode'

const chatStore = useChatStore()
const inputRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()

// Supabase for file upload
const initData = getInitialData()
const supabase = (initData?.supabaseUrl && initData?.supabaseKey)
  ? createClient(initData.supabaseUrl, initData.supabaseKey)
  : null

// Pending files for upload
const pendingFiles = ref<Array<{
  file: File
  id: string
  status: 'pending' | 'uploading' | 'success' | 'error'
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

const canSend = computed(() => {
  const text = chatStore.inputText.trim()
  return text.length > 0 || pendingFiles.value.some(f => f.status === 'success')
})

// Handle file selection
function triggerFileSelect() {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  if (!target.files) return

  const files = Array.from(target.files)
  for (const file of files) {
    const id = Math.random().toString(36).substr(2, 9)
    pendingFiles.value.push({ file, id, status: 'pending' })
  }

  target.value = ''
  await uploadPendingFiles()
}

function removePendingFile(id: string) {
  const idx = pendingFiles.value.findIndex(f => f.id === id)
  if (idx !== -1) pendingFiles.value.splice(idx, 1)
}

async function uploadPendingFiles() {
  if (!supabase) {
    console.warn('Supabase not configured, cannot upload files')
    return
  }

  isUploading.value = true
  for (const record of pendingFiles.value) {
    if (record.status !== 'pending') continue

    record.status = 'uploading'
    try {
      const path = `vscode/${Date.now()}_${record.file.name}`
      const { error } = await supabase.storage.from('upload').upload(path, record.file)
      if (error) throw error

      const { data: { publicUrl } } = supabase.storage.from('upload').getPublicUrl(path)

      record.uploadedData = {
        name: record.file.name,
        url: publicUrl,
        path,
        size: record.file.size,
        type: record.file.type,
      }
      record.status = 'success'
    } catch (error: any) {
      record.status = 'error'
      record.error = error.message || 'Upload failed'
    }
  }
  isUploading.value = false
}

function handleSend() {
  const text = chatStore.inputText.trim()
  console.log('[ChatInput] handleSend called, text:', JSON.stringify(text), 'runnerAlive:', chatStore.runnerAlive)

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

  // Parse @mention
  let cleanText = text
  let targetAgentId: string | undefined

  const mentionMatch = text.match(/@(\w+)/)
  if (mentionMatch) {
    targetAgentId = mentionMatch[1]
    cleanText = text.replace(/@\w+\s*/, '').trim()
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
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}

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
</script>

<template>
  <div class="input-container">
    <!-- File preview area -->
    <div v-if="pendingFiles.length > 0" class="file-preview-area">
      <div
        v-for="record in pendingFiles"
        :key="record.id"
        class="file-item"
        :class="{ 'file-error': record.status === 'error', 'file-success': record.status === 'success' }"
      >
        <span>{{ getFileIcon(record.file) }}</span>
        <span class="file-name">{{ record.file.name }}</span>
        <span class="file-size">{{ formatFileSize(record.file.size) }}</span>
        <span v-if="record.status === 'uploading'" class="upload-status">Uploading...</span>
        <span v-if="record.status === 'error'" class="upload-status error">{{ record.error }}</span>
        <button
          v-if="record.status !== 'uploading'"
          class="file-remove"
          @click="removePendingFile(record.id)"
        >✕</button>
      </div>
    </div>

    <!-- Input row -->
    <div class="input-row">
      <textarea
        ref="inputRef"
        v-model="chatStore.inputText"
        class="chat-input"
        placeholder="Type a message... (use @ to mention an agent)"
        rows="1"
        @keydown="handleKeydown"
      ></textarea>

      <button
        class="tool-button"
        title="Attach file"
        :disabled="!supabase"
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

    <!-- Disabled overlay when runner is not alive -->
    <div v-if="!chatStore.runnerAlive" class="disabled-overlay">
      <template v-if="chatStore.runnerInfo === null">Connecting to runner...</template>
      <template v-else>Runner is not running. Start the runner to send messages.</template>
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

.file-preview-area {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  max-height: 100px;
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
}

.file-item.file-error {
  border: 1px solid var(--error-fg);
}

.file-item.file-success {
  border: 1px solid var(--success-fg);
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

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.chat-input {
  flex: 1;
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
