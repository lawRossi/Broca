<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Warning, Refresh, Headset } from '@element-plus/icons-vue'

// Props
const props = defineProps<{
  /** 文件路径（用于本地文件系统预览） */
  filePath?: string
  /** 文件URL（用于直接预览，如Supabase Storage） */
  fileUrl?: string
  /** 文件信息（可选，如果提供则不需要重新获取） */
  fileInfo?: {
    name: string
    path: string
    size?: number
    type?: string
    url?: string
  }
  /** 是否显示预览对话框 */
  visible?: boolean
}>()

// Emits
const emit = defineEmits<{
  'update:visible': [value: boolean]
  'close': []
}>()

// Reactive state
const previewLoading = ref(false)
const previewContent = ref<string>('')
const previewError = ref<string>('')
const fileExtension = ref<string>('')
const isTextFile = ref(false)
const isImageFile = ref(false)
const isVideoFile = ref(false)
const isAudioFile = ref(false)
const truncated = ref(false)

// 计算属性：显示对话框
const dialogVisible = computed({
  get: () => props.visible || false,
  set: (value) => emit('update:visible', value)
})

// 决定使用哪种预览方式
const previewMode = computed(() => {
  if (props.fileUrl) {
    return 'direct' // 直接使用URL预览（如Supabase Storage）
  }
  if (props.filePath) {
    return 'api' // 通过API预览（本地文件系统）
  }
  return 'none'
})

// 获取文件名
const fileName = computed(() => {
  if (props.fileInfo?.name) {
    return props.fileInfo.name
  }
  if (props.filePath) {
    return props.filePath.split('/').pop() || ''
  }
  if (props.fileUrl) {
    const url = new URL(props.fileUrl)
    return url.pathname.split('/').pop() || ''
  }
  return ''
})

// 文件扩展名映射
const extensionMap: Record<string, { type: string; category: string }> = {
  // 图片
  jpg: { type: 'image/jpeg', category: 'image' },
  jpeg: { type: 'image/jpeg', category: 'image' },
  png: { type: 'image/png', category: 'image' },
  gif: { type: 'image/gif', category: 'image' },
  bmp: { type: 'image/bmp', category: 'image' },
  svg: { type: 'image/svg+xml', category: 'image' },
  webp: { type: 'image/webp', category: 'image' },
  ico: { type: 'image/x-icon', category: 'image' },

  // 视频
  mp4: { type: 'video/mp4', category: 'video' },
  mov: { type: 'video/quicktime', category: 'video' },
  avi: { type: 'video/x-msvideo', category: 'video' },
  wmv: { type: 'video/x-ms-wmv', category: 'video' },
  flv: { type: 'video/x-flv', category: 'video' },
  mkv: { type: 'video/x-matroska', category: 'video' },
  webm: { type: 'video/webm', category: 'video' },

  // 音频
  mp3: { type: 'audio/mpeg', category: 'audio' },
  wav: { type: 'audio/wav', category: 'audio' },
  ogg: { type: 'audio/ogg', category: 'audio' },
  m4a: { type: 'audio/mp4', category: 'audio' },
  aac: { type: 'audio/aac', category: 'audio' },

  // 文档
  pdf: { type: 'application/pdf', category: 'document' },
  doc: { type: 'application/msword', category: 'document' },
  docx: { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', category: 'document' },
  xls: { type: 'application/vnd.ms-excel', category: 'document' },
  xlsx: { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', category: 'document' },
  csv: { type: 'text/csv', category: 'document' },

  // 文本/代码
  txt: { type: 'text/plain', category: 'text' },
  md: { type: 'text/markdown', category: 'text' },
  json: { type: 'application/json', category: 'text' },
  xml: { type: 'application/xml', category: 'text' },
  html: { type: 'text/html', category: 'text' },
  css: { type: 'text/css', category: 'text' },
  js: { type: 'application/javascript', category: 'text' },
  ts: { type: 'application/typescript', category: 'text' },
  py: { type: 'text/x-python', category: 'text' },
  java: { type: 'text/x-java-source', category: 'text' },
  c: { type: 'text/x-c', category: 'text' },
  cpp: { type: 'text/x-c++', category: 'text' },
  h: { type: 'text/x-c', category: 'text' },
  hpp: { type: 'text/x-c++', category: 'text' },
  yaml: { type: 'text/yaml', category: 'text' },
  yml: { type: 'text/yaml', category: 'text' },
  sh: { type: 'application/x-sh', category: 'text' },
  bash: { type: 'application/x-sh', category: 'text' },
  zsh: { type: 'application/x-sh', category: 'text' },
  log: { type: 'text/plain', category: 'text' },
  sql: { type: 'text/x-sql', category: 'text' },
  gitignore: { type: 'text/plain', category: 'text' },
  env: { type: 'text/plain', category: 'text' },

  // 压缩文件
  zip: { type: 'application/zip', category: 'archive' },
  rar: { type: 'application/x-rar-compressed', category: 'archive' },
  '7z': { type: 'application/x-7z-compressed', category: 'archive' },
  tar: { type: 'application/x-tar', category: 'archive' },
  gz: { type: 'application/gzip', category: 'archive' },
  tgz: { type: 'application/gzip', category: 'archive' },
}

// Methods
/** 获取文件扩展名 */
const getFileExtension = (filename: string): string => {
  const parts = filename.split('.')
  return parts.length > 1 ? (parts[parts.length - 1] || '').toLowerCase() : ''
}

/** 判断文件类型 */
const detectFileType = (filename: string, mimeType?: string) => {
  const ext = getFileExtension(filename)
  fileExtension.value = ext

  // 优先使用 MIME 类型判断
  if (mimeType) {
    if (mimeType.startsWith('image/')) {
      isImageFile.value = true
      isVideoFile.value = false
      isAudioFile.value = false
      isTextFile.value = false
      return
    }
    if (mimeType.startsWith('video/')) {
      isImageFile.value = false
      isVideoFile.value = true
      isAudioFile.value = false
      isTextFile.value = false
      return
    }
    if (mimeType.startsWith('audio/')) {
      isImageFile.value = false
      isVideoFile.value = false
      isAudioFile.value = true
      isTextFile.value = false
      return
    }
    if (mimeType.startsWith('text/') || mimeType === 'application/json' || mimeType === 'application/xml') {
      isImageFile.value = false
      isVideoFile.value = false
      isAudioFile.value = false
      isTextFile.value = true
      return
    }
  }

  // 使用扩展名判断
  const extInfo = extensionMap[ext]
  if (extInfo) {
    isImageFile.value = extInfo.category === 'image'
    isVideoFile.value = extInfo.category === 'video'
    isAudioFile.value = extInfo.category === 'audio'
    isTextFile.value = extInfo.category === 'text'
  } else {
    // 默认不可预览
    isImageFile.value = false
    isVideoFile.value = false
    isAudioFile.value = false
    isTextFile.value = false
  }
}

/** 通过API加载文件预览（用于本地文件系统） */
const loadPreviewViaApi = async (path: string) => {
  previewLoading.value = true
  previewError.value = ''
  previewContent.value = ''

  try {
    const response = await fetch(`/files/preview?path=${encodeURIComponent(path)}`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    const result = await response.json()

    if (!result.preview) {
      previewError.value = result.message || 'Cannot preview this file'
      previewContent.value = ''
    } else {
      previewContent.value = result.preview
      truncated.value = result.truncated || false
    }

    // 检测文件类型
    const filename = path.split('/').pop() || ''
    const mimeType = result.mime_type
    detectFileType(filename, mimeType)
  } catch (error: any) {
    console.error('Error previewing file via API:', error)
    previewError.value = `Failed to preview file: ${error.message}`
    ElMessage.error(previewError.value)
  } finally {
    previewLoading.value = false
  }
}

/** 加载文件预览 */
const loadPreview = async () => {
  if (previewMode.value === 'direct' && props.fileUrl) {
    // 直接使用URL预览
    previewLoading.value = true
    previewError.value = ''
    previewContent.value = ''
    const filename = fileName.value
    const fileType = props.fileInfo?.type || ''

    detectFileType(filename, fileType)

    // 对于非文本文件（图片、视频、音频），直接使用URL作为预览内容
    // 对于文本文件，需要获取内容
    if (isTextFile.value) {
      try {
        // 对于 Supabase Storage，尝试获取内容
        const response = await fetch(props.fileUrl)
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }
        const text = await response.text()
        previewContent.value = text
        truncated.value = false
      } catch (error: any) {
        console.error('Error fetching file content:', error)
        // 如果 fetch 失败，可能是 CORS 问题，提示用户在新窗口打开
        previewError.value = 'Cannot preview text file in embedded viewer. Click "Open in New Window" to view.'
        previewContent.value = ''
      }
    } else {
      // 对于媒体文件，将URL放入previewContent，供img/video/audio标签使用
      previewContent.value = props.fileUrl
    }

    previewLoading.value = false
    return
  }

  if (previewMode.value === 'api' && props.filePath) {
    // 通过API预览
    await loadPreviewViaApi(props.filePath)
    return
  }

  previewError.value = 'No valid file source provided'
  previewLoading.value = false
}

/** 关闭预览 */
const closePreview = () => {
  dialogVisible.value = false
  emit('close')
}

/** 在新窗口打开文件 */
const openInNewWindow = () => {
  if (props.fileUrl) {
    window.open(props.fileUrl, '_blank')
  }
}

/** 语法高亮类名 */
const syntaxHighlightClass = computed(() => {
  const ext = fileExtension.value
  const mapping: Record<string, string> = {
    js: 'javascript',
    ts: 'typescript',
    vue: 'vue',
    html: 'html',
    css: 'css',
    py: 'python',
    java: 'java',
    cpp: 'cpp',
    c: 'c',
    xml: 'xml',
    json: 'json',
    md: 'markdown',
    yaml: 'yaml',
    yml: 'yaml',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
  }
  return mapping[ext] || 'plaintext'
})

// Watchers
watch(
  () => props.visible,
  (newVal) => {
    if (newVal) {
      loadPreview()
    }
  }
)

// Expose methods
defineExpose({
  loadPreview,
  closePreview
})
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    :title="`File Preview: ${fileName}`"
    :width="isImageFile ? '80%' : '60%'"
    :fullscreen="isImageFile"
    :close-on-click-modal="true"
    @close="closePreview"
  >
    <div class="file-preview-content">
      <!-- 加载状态 -->
      <div v-if="previewLoading" class="p-8 text-center">
        <el-icon class="is-loading text-3xl text-primary-500">
          <Refresh />
        </el-icon>
        <p class="mt-2 text-gray-600">
          Loading file preview...
        </p>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="previewError" class="p-8 text-center">
        <el-icon class="text-3xl text-red-400">
          <Warning />
        </el-icon>
        <p class="mt-2 text-red-600">
          {{ previewError }}
        </p>
      </div>

      <!-- 图片预览 -->
      <div v-else-if="isImageFile && previewContent" class="image-preview">
        <img
          :src="previewContent"
          alt="Image preview"
          class="max-w-full max-h-[70vh] mx-auto"
          style="object-fit: contain;"
        />
      </div>

      <!-- 视频预览 -->
      <div v-else-if="isVideoFile && previewContent" class="video-preview">
        <video
          :src="previewContent"
          controls
          class="max-w-full max-h-[70vh] mx-auto"
          style="object-fit: contain;"
        >
          Your browser does not support the video tag.
        </video>
      </div>

      <!-- 音频预览 -->
      <div v-else-if="isAudioFile && previewContent" class="audio-preview">
        <div class="text-center mb-4">
          <el-icon class="text-4xl text-blue-500">
            <Headset />
          </el-icon>
        </div>
        <audio
          :src="previewContent"
          controls
          class="w-full max-w-md mx-auto"
        >
          Your browser does not support the audio tag.
        </audio>
      </div>

      <!-- 文本预览 -->
      <div v-else-if="isTextFile && previewContent" class="text-preview">
        <div class="mb-3 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="bg-gray-200 text-gray-700 px-2 py-1 rounded text-xs">
              {{ fileExtension }}
              <span v-if="syntaxHighlightClass !== 'plaintext'" class="ml-1 text-primary-600">●</span>
            </span>
            <span class="text-xs text-gray-500">
              {{ (previewContent.length / 1024).toFixed(2) }} KB
            </span>
            <span v-if="truncated" class="text-yellow-600 text-xs flex items-center gap-1">
              <el-icon><Warning /></el-icon>
              Truncated
            </span>
          </div>
        </div>
        <div class="bg-gray-900 rounded-lg overflow-auto max-h-[60vh] flex">
          <!-- 行号 -->
          <div class="bg-gray-800 text-gray-400 text-right py-4 px-3 select-none border-r border-gray-700">
            <div v-for="(_, index) in previewContent.split('\n')" :key="index" class="leading-6">
              {{ index + 1 }}
            </div>
          </div>
          <!-- 内容 -->
          <pre class="text-gray-100 p-4 text-sm font-mono whitespace-pre-wrap flex-1">{{ previewContent }}</pre>
        </div>
      </div>

      <!-- 无法预览 -->
      <div v-else class="p-8 text-center">
        <el-icon class="text-3xl text-gray-400">
          <Document />
        </el-icon>
        <p class="mt-2 text-gray-600">
          Cannot preview this file type
        </p>
        <p class="text-sm text-gray-500 mt-1">
          Supported: Images, Videos, Audio, Text files, Code files
        </p>
      </div>
    </div>

    <template #footer>
      <div class="w-full flex justify-end gap-2">
        <el-button v-if="previewMode === 'direct' && props.fileUrl" @click="openInNewWindow">
          Open in New Window
        </el-button>
        <el-button @click="closePreview">Close</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.file-preview-content {
  min-height: 200px;
}

.image-preview,
.video-preview,
.audio-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
  border-radius: 8px;
  padding: 16px;
}

.text-preview {
  background: #f5f5f5;
  border-radius: 8px;
  padding: 16px;
}

/* 滚动条样式 */
:deep(.el-dialog__body) {
  padding: 16px 20px;
}

.bg-gray-900::-webkit-scrollbar,
.bg-gray-800::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.bg-gray-900::-webkit-scrollbar-track,
.bg-gray-800::-webkit-scrollbar-track {
  background: #1f2937;
}

.bg-gray-900::-webkit-scrollbar-thumb,
.bg-gray-800::-webkit-scrollbar-thumb {
  background: #4b5563;
  border-radius: 4px;
}

.bg-gray-900::-webkit-scrollbar-thumb:hover,
.bg-gray-800::-webkit-scrollbar-thumb:hover {
  background: #6b7280;
}
</style>
