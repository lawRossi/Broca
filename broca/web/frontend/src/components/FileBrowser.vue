<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Folder, Document, ArrowLeft, Refresh, Search, InfoFilled } from '@element-plus/icons-vue'
import type { FileItem } from '@/api/files'
import { formatUnixTimestamp } from '@/utils/time'

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
const previewFileName = ref('')
const previewLoading = ref(false)
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

// Methods
const loadFiles = async (path: string = currentPath.value) => {
  try {
    loading.value = true
    const response = await fetch(`/api/files?path=${encodeURIComponent(path)}`)
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const data = await response.json()
    
    if (data.code !== 200) {
      throw new Error(data.msg || 'Failed to load files')
    }
    
    const result = data.data
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
    
    const response = await fetch(`/api/files/preview?path=${encodeURIComponent(file.path)}&max_lines=100`)
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const data = await response.json()
    
    if (data.code !== 200) {
      throw new Error(data.msg || 'Failed to preview file')
    }
    
    const result = data.data
    if (result.preview === null) {
      previewContent.value = result.message || 'Cannot preview this file'
    } else {
      previewContent.value = result.preview
      if (result.truncated) {
        previewContent.value += '\n\n... (truncated)'
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

// Lifecycle
onMounted(() => {
  loadFiles()
  checkIsMobile()
  window.addEventListener('resize', handleResize)
})

// 清理事件监听器
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
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
      :title="`Preview: ${previewFileName}`"
      width="90%"
      :fullscreen="isMobile"
    >
      <div v-if="previewLoading" class="p-8 text-center">
        <el-icon class="is-loading text-2xl text-primary-500">
          <Refresh />
        </el-icon>
        <p class="mt-2 text-gray-600">Loading preview...</p>
      </div>
      <pre v-else class="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-auto max-h-[60vh] text-sm font-mono whitespace-pre-wrap">{{ previewContent }}</pre>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showPreview = false">Close</el-button>
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
</style>