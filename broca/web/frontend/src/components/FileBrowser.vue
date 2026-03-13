<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

// 防抖函数
const debounce = (fn: Function, delay: number) => {
  let timeoutId: number
  return (...args: any[]) => {
    clearTimeout(timeoutId)
    timeoutId = setTimeout(() => fn(...args), delay)
  }
}
import { Folder, Document, ArrowLeft, Refresh, Search, InfoFilled, Edit, Warning } from '@element-plus/icons-vue'
import type { FileItem } from '@/api/files'
import { formatUnixTimestamp } from '@/utils/time'
import { filesApi } from '@/api'

// Props
const props = defineProps<{
  initialPath?: string
}>()

// Emits
const emit = defineEmits<{
  'file-click': [file: FileItem]
  'path-change': [path: string]
}>()

// Reactive state
const currentPath = ref(props.initialPath || '.')
const files = ref<FileItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const breadcrumbs = ref<string[]>([])
const showPreview = ref(false)
const previewContent = ref('')
const previewFileName = ref<string>('')
const previewLoading = ref(false)
const isEditing = ref(false)
const editedContent = ref('')
const saveLoading = ref(false)
const showSaveConfirm = ref(false)
const contentChanged = ref(false)
const isMobile = ref(false)

// Computed
const filteredFiles = computed(() => {
  if (!searchQuery.value.trim()) {
    return files.value
  }
  
  const query = searchQuery.value.toLowerCase()
  return files.value.filter(file => 
    file.name.toLowerCase().includes(query) ||
    file.path.toLowerCase().includes(query)
  )
})

const hasParent = computed(() => {
  return breadcrumbs.value.length > 1
})

const fileExtension = computed((): string => {
  const fileName = previewFileName.value
  if (!fileName) return ''
  const parts = fileName.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
})



// 简单的语法高亮映射
const syntaxHighlightClass = computed(() => {
  const ext = fileExtension.value
  const mapping: Record<string, string> = {
    'js': 'javascript',
    'ts': 'typescript',
    'vue': 'vue',
    'html': 'html',
    'css': 'css',
    'py': 'python',
    'java': 'java',
    'cpp': 'cpp',
    'c': 'c',
    'h': 'c',
    'xml': 'xml',
    'json': 'json',
    'md': 'markdown',
    'yaml': 'yaml',
    'yml': 'yaml',
    'sh': 'bash',
    'bash': 'bash',
    'zsh': 'bash'
  }
  return mapping[ext] || 'plaintext'
})

const isTextFile = computed(() => {
  if (!previewContent.value) return false
  return !previewContent.value.includes('Binary file') && 
         !previewContent.value.includes('Cannot preview') &&
         previewContent.value.trim() !== ''
})

// Methods
const loadFiles = async (path: string = currentPath.value) => {
  try {
    loading.value = true
    const result = await filesApi.listFiles(path)
    
    currentPath.value = result.current_path
    files.value = result.files
    
    // 更新面包屑
    updateBreadcrumbs(result.current_path)
    
    emit('path-change', currentPath.value)
    
  } catch (error: any) {
    console.error('Error loading files:', error)
    ElMessage.error(`Failed to load files: ${error.message}`)
  } finally {
    loading.value = false
  }
}

const updateBreadcrumbs = (path: string) => {
  const parts = path.split('/').filter(part => part.trim() !== '')
  breadcrumbs.value = parts.length === 0 ? ['/'] : ['/', ...parts]
}

const navigateTo = (path: string) => {
  if (path === currentPath.value) return
  loadFiles(path)
}

const navigateUp = () => {
  const pathParts = currentPath.value.split('/').filter(part => part.trim() !== '')
  if (pathParts.length > 0) {
    pathParts.pop()
    const newPath = pathParts.length === 0 ? '/' : '/' + pathParts.join('/')
    navigateTo(newPath)
  }
}

const navigateToBreadcrumb = (index: number) => {
  if (index === 0) {
    navigateTo('/')
  } else {
    const path = '/' + breadcrumbs.value.slice(1, index + 1).join('/')
    navigateTo(path)
  }
}

const handleFileClick = (file: FileItem) => {
  if (file.is_dir) {
    navigateTo(file.path)
  } else {
    // 点击文件直接预览
    previewFile(file)
  }
}

const handleInfoClick = (file: FileItem) => {
  // 点击详细信息按钮时触发file-click事件
  emit('file-click', file)
}

const previewFile = async (file: FileItem) => {
  try {
    previewLoading.value = true
    previewFileName.value = file.name
    isEditing.value = false
    
    const result = await filesApi.previewFile(file.path)
    
    if (!result.preview) {
      previewContent.value = result.message || 'Cannot preview this file'
      editedContent.value = ''
    } else {
      previewContent.value = result.preview
      editedContent.value = result.preview
      if (result.truncated) {
        previewContent.value += '\n\n... (truncated due to file size limit)'
        editedContent.value += '\n\n... (truncated due to file size limit)'
      }
    }
    
    showPreview.value = true
    
  } catch (error: any) {
    console.error('Error previewing file:', error)
    ElMessage.error(`Failed to preview file: ${error.message}`)
  } finally {
    previewLoading.value = false
  }
}

const getFileIcon = (file: FileItem) => {
  return file.is_dir ? Folder : Document
}

const getFileSize = (file: FileItem) => {
  if (file.is_dir || file.size === null || file.size === undefined) {
    return '-'
  }
  
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = file.size
  let unitIndex = 0
  
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

const getModifiedTime = (file: FileItem) => {
  if (!file.modified_time) return '-'
  return formatUnixTimestamp(file.modified_time)
}

const startEditing = () => {
  // 找到当前预览的文件
  const currentFile = files.value.find(f => f.name === previewFileName.value)
  if (!currentFile) {
    ElMessage.warning('File not found')
    return
  }
  
  if (!currentFile.readable) {
    ElMessage.warning('File is not readable')
    return
  }
  
  // 检查文件是否可编辑
  if (!isTextFile.value) {
    ElMessage.warning('Cannot edit binary or unsupported files')
    return
  }
  
  // 检查是否有未保存的草稿
  const draftKey = `file_draft_${previewFileName.value}`
  const draftData = localStorage.getItem(draftKey)
  
  if (draftData) {
    try {
      const draft = JSON.parse(draftData)
      const draftAge = Date.now() - draft.timestamp
      const maxDraftAge = 24 * 60 * 60 * 1000 // 24小时
      
      if (draftAge < maxDraftAge) {
        ElMessageBox.confirm(
          `Found unsaved draft from ${new Date(draft.timestamp).toLocaleTimeString()}. Restore it?`,
          'Restore Draft',
          {
            confirmButtonText: 'Restore',
            cancelButtonText: 'Start Fresh',
            type: 'info',
          }
        ).then(() => {
          editedContent.value = draft.content
          isEditing.value = true
          contentChanged.value = true
        }).catch(() => {
          // 清除草稿
          localStorage.removeItem(draftKey)
          isEditing.value = true
        })
        return
      } else {
        // 草稿过期，清除
        localStorage.removeItem(draftKey)
      }
    } catch (e) {
      console.error('Error parsing draft:', e)
      localStorage.removeItem(draftKey)
    }
  }
  
  isEditing.value = true
}

const cancelEditing = () => {
  if (contentChanged.value) {
    // 如果有未保存的更改，提示用户
    ElMessageBox.confirm(
      'You have unsaved changes. Are you sure you want to cancel?',
      'Confirm Cancel',
      {
        confirmButtonText: 'Yes, Cancel',
        cancelButtonText: 'Continue Editing',
        type: 'warning',
      }
    ).then(() => {
      isEditing.value = false
      editedContent.value = previewContent.value
      contentChanged.value = false
      // 清除草稿
      const draftKey = `file_draft_${previewFileName.value}`
      localStorage.removeItem(draftKey)
    }).catch(() => {
      // 用户选择继续编辑
    })
  } else {
    isEditing.value = false
    editedContent.value = previewContent.value
  }
}

const handleContentChange = () => {
  contentChanged.value = editedContent.value !== previewContent.value
}

// 防抖的草稿保存函数
const saveDraft = debounce(() => {
  if (contentChanged.value && previewFileName.value && isEditing.value) {
    const draftKey = `file_draft_${previewFileName.value}`
    const draftData = {
      content: editedContent.value,
      timestamp: Date.now()
    }
    localStorage.setItem(draftKey, JSON.stringify(draftData))
  }
}, 2000) // 2秒防抖

// 修改内容变化处理，添加防抖
const handleContentChangeDebounced = () => {
  handleContentChange()
  saveDraft()
}

const handleClosePreview = () => {
  if (isEditing.value && contentChanged.value) {
    ElMessageBox.confirm(
      'You have unsaved changes. Are you sure you want to close?',
      'Confirm Close',
      {
        confirmButtonText: 'Yes, Close',
        cancelButtonText: 'Continue Editing',
        type: 'warning',
      }
    ).then(() => {
      showPreview.value = false
      isEditing.value = false
      contentChanged.value = false
      // 清除草稿
      const draftKey = `file_draft_${previewFileName.value}`
      localStorage.removeItem(draftKey)
    }).catch(() => {
      // 用户选择继续编辑
    })
  } else {
    showPreview.value = false
    isEditing.value = false
    contentChanged.value = false
  }
}

const confirmSave = () => {
  showSaveConfirm.value = true
}

const saveFile = async () => {
  try {
    saveLoading.value = true
    showSaveConfirm.value = false
    
    // 找到当前预览的文件
    const currentFile = files.value.find(f => f.name === previewFileName.value)
    if (!currentFile) {
      throw new Error('File not found')
    }
    
    // 检查文件大小（10MB限制）
    const contentSize = new Blob([editedContent.value]).size
    const maxSize = 10 * 1024 * 1024 // 10MB
    if (contentSize > maxSize) {
      throw new Error(`File content too large (${(contentSize / 1024 / 1024).toFixed(2)}MB > 10MB). Please reduce file size.`)
    }
    
    // 检查文件是否为空
    if (editedContent.value.trim() === '') {
      ElMessageBox.confirm(
        'File content is empty. Save empty file?',
        'Confirm Save',
        {
          confirmButtonText: 'Save Empty',
          cancelButtonText: 'Cancel',
          type: 'warning',
        }
      ).then(() => {
        // 用户确认保存空文件
        performSave(currentFile)
      }).catch(() => {
        saveLoading.value = false
      })
      return
    }
    
    await performSave(currentFile)
    
  } catch (error: any) {
    console.error('Error saving file:', error)
    ElMessage.error(`Failed to save file: ${error.message}`)
    saveLoading.value = false
  }
}

const performSave = async (currentFile: FileItem) => {
  try {
    const result = await filesApi.editFile(currentFile.path, editedContent.value)
    
    // 更新预览内容
    previewContent.value = editedContent.value
    isEditing.value = false
    contentChanged.value = false
    
    // 清除草稿
    const draftKey = `file_draft_${previewFileName.value}`
    localStorage.removeItem(draftKey)
    
    // 更新文件列表中的修改时间
    const updatedFile = files.value.find(f => f.name === previewFileName.value)
    if (updatedFile) {
      updatedFile.modified_time = result.modified_time
    }
    
    ElMessage.success({
      message: `File "${previewFileName.value}" saved successfully`,
      duration: 3000,
      showClose: true
    })
    
  } catch (error: any) {
    console.error('Error in performSave:', error)
    throw error
  } finally {
    saveLoading.value = false
  }
}

const refresh = () => {
  loadFiles()
}

// 检查是否是移动端
const checkIsMobile = () => {
  isMobile.value = window.innerWidth < 768
}

// 监听窗口大小变化
const handleResize = () => {
  checkIsMobile()
}

// 键盘快捷键处理
const handleKeyDown = (event: KeyboardEvent) => {
  if (showPreview.value && isEditing.value) {
    // Ctrl+S 保存
    if ((event.ctrlKey || event.metaKey) && event.key === 's') {
      event.preventDefault()
      confirmSave()
    }
    // Esc 取消编辑
    if (event.key === 'Escape') {
      event.preventDefault()
      if (contentChanged.value) {
        cancelEditing()
      } else {
        isEditing.value = false
      }
    }
  }
}

// Lifecycle
onMounted(() => {
  loadFiles()
  checkIsMobile()
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleKeyDown)
})

// 清理事件监听器
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleKeyDown)
})

// Watch for prop changes
watch(() => props.initialPath, (newPath) => {
  if (newPath && newPath !== currentPath.value) {
    navigateTo(newPath)
  }
})
</script>

<template>
  <div class="file-browser h-full flex flex-col">
    <!-- Header -->
    <div class="bg-white border-b border-gray-200 p-3 sm:p-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <!-- Breadcrumbs -->
        <div class="flex items-center gap-2 overflow-x-auto scrollbar-thin">
          <el-button
            :icon="ArrowLeft"
            size="small"
            :disabled="!hasParent || loading"
            @click="navigateUp"
            class="shrink-0"
          >
            Back
          </el-button>
          
          <div class="flex items-center gap-1 text-sm">
            <span 
              v-for="(crumb, index) in breadcrumbs" 
              :key="index"
              class="flex items-center"
            >
              <span
                class="px-2 py-1 rounded hover:bg-gray-100 cursor-pointer transition-colors"
                :class="{
                  'text-gray-600 hover:text-gray-900': index < breadcrumbs.length - 1,
                  'text-gray-900 font-semibold': index === breadcrumbs.length - 1
                }"
                @click="navigateToBreadcrumb(index)"
              >
                {{ crumb === '/' && index === 0 ? 'Root' : crumb }}
              </span>
              <span 
                v-if="index < breadcrumbs.length - 1" 
                class="text-gray-400 mx-1"
              >
                /
              </span>
            </span>
          </div>
        </div>
        
        <!-- Actions -->
        <div class="flex items-center gap-2 shrink-0">
          <el-input
            v-model="searchQuery"
            :prefix-icon="Search"
            placeholder="Search files..."
            size="small"
            class="w-full sm:w-48"
            clearable
          />
          <el-button
            :icon="Refresh"
            size="small"
            :loading="loading"
            @click="refresh"
            title="Refresh"
          />
        </div>
      </div>
    </div>
    
    <!-- File List -->
    <div class="flex-1 overflow-auto bg-gray-50">
      <div v-if="loading" class="p-8 text-center">
        <el-icon class="is-loading text-2xl text-primary-500">
          <Refresh />
        </el-icon>
        <p class="mt-2 text-gray-600">Loading files...</p>
      </div>
      
      <div v-else-if="filteredFiles.length === 0" class="p-8 text-center">
        <el-icon class="text-3xl text-gray-400">
          <Document />
        </el-icon>
        <p class="mt-2 text-gray-600">
          {{ searchQuery ? 'No files match your search' : 'No files in this directory' }}
        </p>
      </div>
      
      <div v-else class="p-2 sm:p-4">
        <!-- Desktop View -->
        <div class="hidden md:block">
          <div class="bg-white rounded-lg border overflow-hidden">
            <table class="w-full">
              <thead class="bg-gray-50 border-b">
                <tr>
                  <th class="text-left p-3 text-xs font-semibold text-gray-700 uppercase tracking-wider">Name</th>
                  <th class="text-left p-3 text-xs font-semibold text-gray-700 uppercase tracking-wider">Size</th>
                  <th class="text-left p-3 text-xs font-semibold text-gray-700 uppercase tracking-wider">Modified</th>
                  <th class="text-left p-3 text-xs font-semibold text-gray-700 uppercase tracking-wider">Permissions</th>
                  <th class="text-left p-3 text-xs font-semibold text-gray-700 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200">
                <tr 
                  v-for="file in filteredFiles" 
                  :key="file.path"
                  class="hover:bg-gray-50 transition-colors"
                  :class="{ 'bg-blue-50': file.is_dir }"
                >
                  <td class="p-3">
                    <div 
                      class="flex items-center gap-2 cursor-pointer"
                      @click="handleFileClick(file)"
                    >
                      <el-icon :size="18" :class="file.is_dir ? 'text-blue-500' : 'text-gray-500'">
                        <component :is="getFileIcon(file)" />
                      </el-icon>
                      <span class="font-medium text-gray-900">{{ file.name }}</span>
                      <span v-if="!file.readable" class="text-xs text-red-500" title="Not readable">
                        🔒
                      </span>
                    </div>
                  </td>
                  <td class="p-3 text-sm text-gray-600">
                    {{ getFileSize(file) }}
                  </td>
                  <td class="p-3 text-sm text-gray-600">
                    {{ getModifiedTime(file) }}
                  </td>
                  <td class="p-3 text-sm text-gray-600 font-mono">
                    {{ file.permissions }}
                  </td>
                  <td class="p-3">
                    <div class="flex items-center gap-2">
                      <el-button
                        :icon="InfoFilled"
                        size="small"
                        type="text"
                        @click.stop="() => handleInfoClick(file)"
                        title="Details"
                      />
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        
        <!-- Mobile View -->
        <div class="md:hidden">
          <div class="space-y-2">
            <div 
              v-for="file in filteredFiles" 
              :key="file.path"
              class="bg-white rounded-lg border p-3 hover:shadow-sm transition-shadow"
              :class="{ 'border-blue-200 bg-blue-50': file.is_dir }"
            >
              <div class="flex items-start justify-between">
                <div 
                  class="flex-1 cursor-pointer"
                  @click="handleFileClick(file)"
                >
                  <div class="flex items-center gap-2 mb-1">
                    <el-icon :size="16" :class="file.is_dir ? 'text-blue-500' : 'text-gray-500'">
                      <component :is="getFileIcon(file)" />
                    </el-icon>
                    <span class="font-medium text-gray-900 text-sm">{{ file.name }}</span>
                    <span v-if="!file.readable" class="text-xs text-red-500" title="Not readable">
                      🔒
                    </span>
                  </div>
                  
                  <div class="text-xs text-gray-600 space-y-1 ml-6">
                    <div class="flex items-center gap-2">
                      <span v-if="!file.is_dir">
                        Size: {{ getFileSize(file) }}
                      </span>
                      <span class="text-gray-400">•</span>
                      <span>Modified: {{ getModifiedTime(file) }}</span>
                    </div>
                    <div class="font-mono">
                      {{ file.permissions }}
                    </div>
                  </div>
                </div>
                

              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Footer -->
    <div class="bg-white border-t border-gray-200 p-2 sm:p-3">
      <div class="flex items-center justify-between text-xs text-gray-600">
        <div>
          Showing {{ filteredFiles.length }} of {{ files.length }} items
          <span v-if="searchQuery" class="text-primary-600">
            (filtered)
          </span>
        </div>
        <div>
          Path: <code class="ml-1 bg-gray-100 px-2 py-1 rounded">{{ currentPath }}</code>
        </div>
      </div>
    </div>
    
    <!-- File Preview Dialog -->
    <el-dialog
      v-model="showPreview"
      :title="`${isEditing ? 'Edit' : 'Preview'}: ${previewFileName}`"
      width="90%"
      :fullscreen="isMobile"
    >
      <div v-if="previewLoading" class="p-8 text-center">
        <el-icon class="is-loading text-2xl text-primary-500">
          <Refresh />
        </el-icon>
        <p class="mt-2 text-gray-600">Loading preview...</p>
      </div>
      
      <div v-else-if="previewContent === null || previewContent === ''" class="p-8 text-center">
        <el-icon class="text-3xl text-gray-400">
          <Document />
        </el-icon>
        <p class="mt-2 text-gray-600">Cannot preview this file</p>
      </div>
      
      <div v-else>
        <!-- Preview Mode -->
        <div v-if="!isEditing">
          <div class="mb-4 flex items-center justify-between">
            <div class="text-sm text-gray-600 flex items-center gap-2">
              <span v-if="fileExtension" class="bg-gray-200 text-gray-700 px-2 py-1 rounded text-xs">
                {{ fileExtension }}
                <span v-if="syntaxHighlightClass !== 'plaintext'" class="ml-1 text-primary-600">
                  ●
                </span>
              </span>
              <span v-if="previewContent && !previewContent.includes('Cannot preview')" class="text-xs text-gray-500">
                {{ (previewContent.length / 1024).toFixed(2) }} KB
              </span>
              <span v-if="previewContent.includes('truncated')" class="text-yellow-600 text-xs">
                <el-icon><Warning /></el-icon>
                Truncated
              </span>
            </div>
            <el-button
              type="primary"
              size="small"
              @click="startEditing"
              :disabled="!isTextFile"
              :title="!isTextFile ? 'Cannot edit this file type' : 'Edit file'"
            >
              <el-icon><Edit /></el-icon>
              Edit
            </el-button>
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
        
        <!-- Edit Mode -->
        <div v-else>
          <div class="mb-4 flex items-center justify-between">
            <div class="text-sm text-gray-600">
              <el-icon><Edit /></el-icon>
              Editing mode
              <span class="ml-2 text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded">
                {{ editedContent.split('\n').length }} lines, {{ editedContent.length }} chars
              </span>
            </div>
            <div class="flex items-center gap-2">
              <el-button
                size="small"
                @click="cancelEditing"
              >
                Cancel
              </el-button>
              <el-button
                type="primary"
                size="small"
                @click="confirmSave"
                :loading="saveLoading"
              >
                Save
              </el-button>
            </div>
          </div>
          <div class="bg-gray-900 rounded-lg overflow-auto max-h-[60vh] flex border border-gray-700">
            <!-- 行号 -->
            <div class="bg-gray-800 text-gray-400 text-right py-4 px-3 select-none border-r border-gray-700 flex-shrink-0">
              <div v-for="(_, index) in editedContent.split('\n')" :key="index" class="leading-6">
                {{ index + 1 }}
              </div>
            </div>
            <!-- 内容编辑区 -->
            <textarea
              v-model="editedContent"
              class="flex-1 font-mono text-sm bg-gray-900 text-gray-100 p-4 resize-none focus:outline-none"
              spellcheck="false"
              placeholder="Edit file content..."
              @input="handleContentChangeDebounced"
            ></textarea>
          </div>
          <div class="mt-2 text-xs text-gray-500 flex justify-between">
            <div>
              <el-icon><InfoFilled /></el-icon>
              Press Ctrl+S to save, Esc to cancel
            </div>
            <div v-if="contentChanged" class="text-yellow-600">
              <el-icon><Warning /></el-icon>
              Unsaved changes
            </div>
          </div>
        </div>
      </div>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="handleClosePreview">Close</el-button>
          <el-button
            v-if="!isEditing && isTextFile"
            type="primary"
            @click="startEditing"
          >
            Edit
          </el-button>
          <el-button
            v-if="isEditing"
            @click="cancelEditing"
          >
            Cancel
          </el-button>
          <el-button
            v-if="isEditing"
            type="primary"
            @click="confirmSave"
            :loading="saveLoading"
          >
            Save
          </el-button>
        </span>
      </template>
    </el-dialog>
    
    <!-- Save Confirmation Dialog -->
    <el-dialog
      v-model="showSaveConfirm"
      title="Confirm Save"
      width="400px"
    >
      <div class="space-y-4">
        <div class="flex items-start gap-3">
          <el-icon class="text-yellow-500 mt-0.5"><Warning /></el-icon>
          <div>
            <p class="font-medium text-gray-900">Are you sure you want to save changes?</p>
            <p class="text-sm text-gray-600 mt-1">
              This will overwrite the original file. A backup will be created with .bak extension.
            </p>
          </div>
        </div>
      </div>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showSaveConfirm = false">Cancel</el-button>
          <el-button type="primary" @click="saveFile" :loading="saveLoading">
            Save Changes
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.file-browser {
  min-height: 500px;
}

/* Responsive table */
@media (max-width: 767px) {
  .file-browser {
    min-height: 400px;
  }
}

/* Scrollbar styling */
.scrollbar-thin::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}

.scrollbar-thin::-webkit-scrollbar-track {
  background: #f1f5f9;
}

.scrollbar-thin::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}

.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* 预览对话框样式优化 */
:deep(.el-dialog__body) {
  padding-top: 10px !important;
}

/* 文本区域样式 */
textarea {
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
  line-height: 1.5;
}

/* 行号区域样式 */
.line-numbers {
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
  font-size: 12px;
  user-select: none;
}

/* 语法高亮提示 */
.syntax-badge {
  font-size: 10px;
  opacity: 0.7;
}
</style>