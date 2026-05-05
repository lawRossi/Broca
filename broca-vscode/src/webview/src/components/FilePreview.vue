<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  filePath?: string
  fileUrl?: string
}>()

const emit = defineEmits<{
  close: []
}>()

const loading = ref(false)
const content = ref('')
const error = ref('')
const fileName = ref('')

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      loadContent()
    } else {
      content.value = ''
      error.value = ''
      fileName.value = ''
    }
  }
)

async function loadContent() {
  loading.value = true
  error.value = ''

  try {
    if (props.fileUrl) {
      // Fetch from URL
      const response = await fetch(props.fileUrl)
      if (!response.ok) throw new Error(`Failed to fetch: ${response.statusText}`)
      const text = await response.text()
      content.value = text
      fileName.value = props.fileUrl.split('/').pop() || 'file'
    } else if (props.filePath) {
      // Try to open via postMessage to extension host
      content.value = 'Loading file from workspace...'
      // The extension host should handle opening files
      // For now, we'll show a placeholder
      const { postMessage } = await import('../api/vscode')
      postMessage({
        type: 'openFile',
        payload: { path: props.filePath },
      })
      content.value = `Opening file: ${props.filePath}`
      fileName.value = props.filePath.split('/').pop() || 'file'
    }
  } catch (e: any) {
    error.value = e.message || 'Failed to load file'
  } finally {
    loading.value = false
  }
}

function getFileExtension(name: string): string {
  return name.split('.').pop()?.toLowerCase() || ''
}

const isImage = ref(false)
watch(
  () => props.fileUrl,
  (url) => {
    if (url) {
      const ext = getFileExtension(url)
      isImage.value = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'].includes(ext)
    }
  },
  { immediate: true }
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="preview-overlay" @click.self="emit('close')">
      <div class="preview-container">
        <div class="preview-header">
          <span class="preview-title">{{ fileName || 'File Preview' }}</span>
          <button class="close-btn" @click="emit('close')">✕</button>
        </div>
        <div class="preview-body">
          <div v-if="loading" class="preview-loading">
            <span>Loading...</span>
          </div>
          <div v-else-if="error" class="preview-error">
            <span class="error-icon">⚠️</span>
            <span>{{ error }}</span>
          </div>
          <div v-else-if="isImage && fileUrl" class="preview-image">
            <img :src="fileUrl" :alt="fileName" />
          </div>
          <div v-else class="preview-text">
            <pre>{{ content }}</pre>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.preview-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.preview-container {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  width: 80vw;
  max-width: 900px;
  height: 70vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.preview-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  padding: 4px 8px;
  border-radius: 4px;
}

.close-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.preview-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.preview-loading,
.preview-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 100%;
  font-size: 14px;
  color: var(--text-secondary);
}

.error-icon {
  font-size: 20px;
}

.preview-image {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.preview-image img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
}

.preview-text pre {
  margin: 0;
  font-family: var(--code-font-family);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-primary);
}
</style>
