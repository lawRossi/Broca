<script setup lang="ts">
import { computed, onMounted, watch, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore, useSessionStore } from '@/stores'
import type { Session } from '@/api/session'
import type { FileItem } from '@/api/files'
import { jobApi } from '@/api/job'
import { ChatRound, Plus } from '@element-plus/icons-vue'

// 导入拆分出的组件
import SessionSearchFilter from '@/components/SessionSearchFilter.vue'
import SessionList from '@/components/SessionList.vue'
import CreateSessionDialog from '@/components/CreateSessionDialog.vue'
import WorkspacePicker from '@/components/WorkspacePicker.vue'

const router = useRouter()
const userStore = useUserStore()
const sessionStore = useSessionStore()

// 计算属性（从store获取）
const sessions = computed(() => sessionStore.sessions)
const loading = computed(() => sessionStore.loading)
const total = computed(() => sessionStore.total)
const currentPage = computed(() => sessionStore.currentPage)
const pageSize = computed(() => sessionStore.pageSize)
const searchKeyword = computed(() => sessionStore.searchKeyword)
const selectedSessions = computed(() => sessionStore.selectedSessions)
const createDialogVisible = computed(() => sessionStore.createDialogVisible)
const creating = computed(() => sessionStore.creating)
const deleteLoading = computed(() => sessionStore.deleteLoading)
const createForm = computed(() => sessionStore.createForm)
const workspaceAllSuggestions = computed(() => sessionStore.workspaceAllSuggestions)
const workspacePickerVisible = computed(() => sessionStore.workspacePickerVisible)

// Session job counts
const jobCounts = ref<Record<string, number>>({})
const loadingJobCounts = ref(false)

// 计算属性：是否已登录
const isLoggedIn = computed(() => userStore.isLoggedIn)

// 搜索
const handleSearch = (keyword: string) => {
  sessionStore.setSearchKeyword(keyword)
}

// 分页
const handlePageChange = (page: number) => {
  sessionStore.setCurrentPage(page)
  sessionStore.fetchSessions()
}

const handleSizeChange = (size: number) => {
  sessionStore.setPageSize(size)
}

// 选择会话
const handleSelect = (sessionId: string) => {
  sessionStore.selectSession(sessionId)
}

const handleDeselect = (sessionId: string) => {
  sessionStore.deselectSession(sessionId)
}

// 创建会话
const handleCreate = async () => {
  const response = await sessionStore.createSession(createForm.value)
  if (response?.session_id) {
    router.push(`/chat/${response.session_id}`)
  }
}

// 删除单个会话
const handleDelete = async (session: Session) => {
  await sessionStore.deleteSession(session.session_id)
}

// 更新会话
const handleUpdate = async (session: Session) => {
  // 更新已经在store中处理了，这里只需要更新本地状态
  // 如果需要额外的处理可以在这里添加
}

// 批量删除会话
const handleBatchDelete = async () => {
  await sessionStore.deleteSessions(selectedSessions.value)
}

// 工作空间选择
const handleWorkspaceSelect = (file: FileItem) => {
  sessionStore.selectWorkspaceFromPicker(file)
}

const handleWorkspaceConfirm = (path: string) => {
  sessionStore.handleWorkspaceConfirm(path)
}

// 打开工作空间选择器
const openWorkspacePicker = () => {
  sessionStore.setWorkspacePickerVisible(true)
}

// 显示创建会话弹窗
const showCreateDialog = () => {
  sessionStore.extractWorkspaceSuggestions()
  sessionStore.setCreateDialogVisible(true)
}

// 获取所有会话的定时任务数量
const fetchJobCounts = async () => {
  const sessionList = sessions.value
  if (sessionList.length === 0) {
    jobCounts.value = {}
    return
  }

  loadingJobCounts.value = true
  try {
    const counts: Record<string, number> = {}
    // 并行请求所有会话的任务数量
    await Promise.all(
      sessionList.map(async (session) => {
        try {
          const response = await jobApi.getJobs({
            session_id: session.session_id,
            limit: 0, // 只获取总数，不获取具体数据
          })
          counts[session.session_id] = response.total
        } catch (error) {
          console.error(`Failed to fetch job count for session ${session.session_id}:`, error)
          counts[session.session_id] = 0
        }
      })
    )
    jobCounts.value = counts
  } finally {
    loadingJobCounts.value = false
  }
}

// 监听筛选条件变化
watch(
  searchKeyword,
  () => {
    sessionStore.fetchSessions()
  },
  { deep: true }
)

// 监听 sessions 列表变化，重新获取 job counts
watch(
  sessions,
  () => {
    if (sessions.value.length > 0) {
      fetchJobCounts()
    }
  },
  { deep: true }
)

// 组件挂载
onMounted(async () => {
  await userStore.init()
  if (!isLoggedIn.value) {
    router.push('/auth')
    return
  }
  // 获取home目录
  await sessionStore.fetchHomeDirectory()
  await sessionStore.fetchSessions()
  await fetchJobCounts()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 页面标题栏 -->
    <div class="sticky top-0 z-10 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <div class="flex items-center gap-3">
            <el-icon class="text-blue-600 text-xl">
              <ChatRound />
            </el-icon>
            <h1 class="text-xl font-bold text-gray-900">会话管理</h1>
          </div>
          <div class="flex items-center gap-4">
            <div class="text-sm text-gray-500">共 {{ total }} 个会话</div>
            <el-button type="primary" :icon="Plus" @click="showCreateDialog"> 创建会话 </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6 pb-20">
      <!-- 搜索和筛选栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-4 mb-6">
        <SessionSearchFilter
          :search-keyword="searchKeyword"
          :is-logged-in="isLoggedIn"
          @update:search-keyword="handleSearch"
          @create="showCreateDialog"
        />
      </div>

      <!-- 会话列表 -->
      <SessionList
        :sessions="sessions"
        :loading="loading"
        :total="total"
        :current-page="currentPage"
        :page-size="pageSize"
        :selected-sessions="selectedSessions"
        :delete-loading="deleteLoading"
        :job-counts="jobCounts"
        @page-change="handlePageChange"
        @size-change="handleSizeChange"
        @select="handleSelect"
        @deselect="handleDeselect"
        @delete="handleDelete"
        @update="handleUpdate"
        @batch-delete="handleBatchDelete"
      />
    </div>
  </div>

  <!-- 创建会话弹窗 -->
  <CreateSessionDialog
    :visible="createDialogVisible"
    :form-data="createForm"
    :workspace-suggestions="workspaceAllSuggestions"
    :creating="creating"
    @update:visible="sessionStore.setCreateDialogVisible($event)"
    @update:form-data="sessionStore.setCreateForm($event)"
    @create="handleCreate"
    @open-workspace-picker="openWorkspacePicker"
  />

  <!-- 工作空间选择器 -->
  <WorkspacePicker
    :visible="workspacePickerVisible"
    :initial-path="createForm.workspace || sessionStore.homeDirectory"
    @update:visible="sessionStore.setWorkspacePickerVisible($event)"
    @select="handleWorkspaceSelect"
    @confirm="handleWorkspaceConfirm"
  />
</template>

<style scoped>
/* 移动端优化 */
@media (max-width: 640px) {
  :deep(.el-pagination) {
    justify-content: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  :deep(.el-pagination .el-pagination__sizes) {
    margin-right: 0;
  }

  :deep(.el-pagination .el-pagination__total) {
    display: none;
  }
}
</style>
