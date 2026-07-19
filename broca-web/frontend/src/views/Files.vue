<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { House } from '@element-plus/icons-vue'
// FolderOpened可能不可用，使用Folder代替
import { Folder } from '@element-plus/icons-vue'
import FileBrowser from '@/components/FileBrowser.vue'
import type { FileItem } from '@/api/files'
import { useUserStore } from '@/stores'
import { formatUnixTime } from '@/utils/time'
import { filesApi } from '@/api'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// State
const currentPath = ref((route.query.path as string) || '.')
const fileInfoDialog = ref(false)
const selectedFile = ref<FileItem | null>(null)
const fileInfoLoading = ref(false)
const fileInfo = ref<any>(null)
const isMobile = ref(false)

// Methods
const handleFileClick = (file: FileItem) => {
  selectedFile.value = file
  if (file.is_dir) {
    // 目录点击已经在FileBrowser中处理了
    return
  }

  // 对于文件，显示详细信息（通过InfoFilled按钮触发）
  showFileInfo(file)
}

const handlePathChange = (path: string) => {
  currentPath.value = path
}

const showFileInfo = async (file: FileItem) => {
  try {
    fileInfoLoading.value = true
    fileInfo.value = await filesApi.getFileInfo(file.path)
    fileInfoDialog.value = true
  } catch (error: any) {
    console.error('Error getting file info:', error)
    ElMessage.error(`Failed to get file info: ${error.message}`)
  } finally {
    fileInfoLoading.value = false
  }
}

const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B'

  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 使用工具函数

const goHome = () => {
  router.push('/')
}

// 检查是否是移动端
const checkIsMobile = () => {
  isMobile.value = window.innerWidth < 768
}

// 监听窗口大小变化
const handleResize = () => {
  checkIsMobile()
}

// 监听路由查询参数变化
watch(
  () => route.query.path,
  (newPath) => {
    if (newPath) {
      currentPath.value = newPath as string
    }
  }
)

// Lifecycle
onMounted(async () => {
  // 初始化用户状态
  // await userStore.init()

  // // 检查登录状态
  // if (!userStore.isLoggedIn) {
  //   ElMessage.warning('请先登录')
  //   router.push('/auth')
  //   return
  // }

  checkIsMobile()
  window.addEventListener('resize', handleResize)
})

// 清理事件监听器
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <div class="files-page min-h-screen bg-gray-50">
    <!-- Header -->
    <header class="bg-white border-b border-gray-200 shadow-sm">
      <div class="container mx-auto px-4 py-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="flex items-center gap-2">
              <el-icon :size="24" class="text-primary-600">
                <Folder />
              </el-icon>
              <h1 class="text-xl font-semibold text-gray-900">File Browser</h1>
            </div>
            <span class="text-sm text-gray-500 hidden sm:inline"> Browse and manage files </span>
          </div>

          <div class="flex items-center gap-2">
            <el-button :icon="House" size="small" title="Go Home" @click="goHome">
              <span class="hidden sm:inline">Home</span>
            </el-button>
          </div>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="container mx-auto px-4 py-6">
      <div class="bg-white rounded-xl border shadow-sm overflow-hidden">
        <!-- File Browser Component -->
        <FileBrowser :initial-path="currentPath" @file-click="handleFileClick" @path-change="handlePathChange" />
      </div>
    </main>

    <!-- File Info Dialog -->
    <el-dialog v-model="fileInfoDialog" title="File Information" width="500px" :fullscreen="isMobile">
      <div v-if="fileInfoLoading" class="p-8 text-center">
        <el-icon class="is-loading text-2xl text-primary-500">
          <House />
        </el-icon>
        <p class="mt-2 text-gray-600">Loading file information...</p>
      </div>

      <div v-else-if="fileInfo" class="space-y-4">
        <!-- Basic Info -->
        <div class="bg-gray-50 p-4 rounded-lg">
          <h4 class="font-semibold text-gray-900 mb-3">Basic Information</h4>
          <div class="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span class="text-gray-600">Name:</span>
              <div class="font-medium text-gray-900 mt-1">
                {{ fileInfo.name }}
              </div>
            </div>
            <div>
              <span class="text-gray-600">Type:</span>
              <div class="font-medium text-gray-900 mt-1">
                {{ fileInfo.is_dir ? 'Directory' : 'File' }}
              </div>
            </div>
            <div>
              <span class="text-gray-600">Path:</span>
              <div class="font-medium text-gray-900 mt-1 truncate" :title="fileInfo.path">
                {{ fileInfo.path }}
              </div>
            </div>
            <div v-if="!fileInfo.is_dir">
              <span class="text-gray-600">Size:</span>
              <div class="font-medium text-gray-900 mt-1">
                {{ formatBytes(fileInfo.size) }}
              </div>
            </div>
          </div>
        </div>

        <!-- Timestamps -->
        <div class="bg-gray-50 p-4 rounded-lg">
          <h4 class="font-semibold text-gray-900 mb-3">Timestamps</h4>
          <div class="space-y-2 text-sm">
            <div class="flex justify-between">
              <span class="text-gray-600">Created:</span>
              <span class="font-medium text-gray-900">{{ formatUnixTime(fileInfo.created_time) }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-600">Modified:</span>
              <span class="font-medium text-gray-900">{{ formatUnixTime(fileInfo.modified_time) }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-600">Accessed:</span>
              <span class="font-medium text-gray-900">{{ formatUnixTime(fileInfo.accessed_time) }}</span>
            </div>
          </div>
        </div>

        <!-- Permissions -->
        <div class="bg-gray-50 p-4 rounded-lg">
          <h4 class="font-semibold text-gray-900 mb-3">Permissions</h4>
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <div>
                <div class="font-mono text-lg">
                  {{ fileInfo.permissions }}
                </div>
                <div class="text-xs text-gray-500 mt-1">Unix permissions</div>
              </div>
              <div class="flex items-center gap-4">
                <div class="text-center">
                  <div class="text-2xl" :class="fileInfo.readable ? 'text-green-600' : 'text-red-600'">
                    {{ fileInfo.readable ? '✓' : '✗' }}
                  </div>
                  <div class="text-xs text-gray-600 mt-1">Read</div>
                </div>
                <div class="text-center">
                  <div class="text-2xl" :class="fileInfo.writable ? 'text-green-600' : 'text-red-600'">
                    {{ fileInfo.writable ? '✓' : '✗' }}
                  </div>
                  <div class="text-xs text-gray-600 mt-1">Write</div>
                </div>
                <div class="text-center">
                  <div class="text-2xl" :class="fileInfo.executable ? 'text-green-600' : 'text-red-600'">
                    {{ fileInfo.executable ? '✓' : '✗' }}
                  </div>
                  <div class="text-xs text-gray-600 mt-1">Execute</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- System Info -->
        <div class="bg-gray-50 p-4 rounded-lg">
          <h4 class="font-semibold text-gray-900 mb-3">System Information</h4>
          <div class="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span class="text-gray-600">Inode:</span>
              <div class="font-medium text-gray-900 mt-1">
                {{ fileInfo.inode }}
              </div>
            </div>
            <div>
              <span class="text-gray-600">Device:</span>
              <div class="font-medium text-gray-900 mt-1">
                {{ fileInfo.device }}
              </div>
            </div>
            <div>
              <span class="text-gray-600">Hard Links:</span>
              <div class="font-medium text-gray-900 mt-1">
                {{ fileInfo.hard_links }}
              </div>
            </div>
            <div>
              <span class="text-gray-600">Owner (UID/GID):</span>
              <div class="font-medium text-gray-900 mt-1">{{ fileInfo.uid }}/{{ fileInfo.gid }}</div>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="fileInfoDialog = false">Close</el-button>
          <el-button v-if="selectedFile && !selectedFile.is_dir" type="primary" @click="showFileInfo(selectedFile)">
            Preview
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.files-page {
  min-height: 100vh;
}

/* Responsive adjustments */
@media (max-width: 640px) {
  .files-page {
    padding-bottom: env(safe-area-inset-bottom);
  }

  .container {
    padding-left: 1rem;
    padding-right: 1rem;
  }
}

/* Dialog fullscreen on mobile */
:deep(.el-dialog) {
  margin: 0 !important;
}

@media (max-width: 639px) {
  :deep(.el-dialog) {
    width: 100% !important;
    height: 100% !important;
    border-radius: 0 !important;
  }

  :deep(.el-dialog__body) {
    padding: 1rem !important;
  }
}
</style>
