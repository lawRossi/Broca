<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores'
import { sessionApi, type Session, type CreateSessionParams } from '@/api/session'
import type { FileItem } from '@/api/files'
import { ChatRound, Plus } from '@element-plus/icons-vue'

// 导入拆分出的组件
import SessionSearchFilter from '@/components/SessionSearchFilter.vue'
import SessionList from '@/components/SessionList.vue'
import CreateSessionDialog from '@/components/CreateSessionDialog.vue'
import WorkspacePicker from '@/components/WorkspacePicker.vue'

const router = useRouter()
const userStore = useUserStore()

// LLM Model 选项（传递给 CreateSessionDialog 的 availableModels 计算使用）
const LLM_MODELS: Record<string, { label: string; value: string }[]> = {
  openrouter: [
    { label: 'StepFun (Step-3.5-Flash)', value: 'stepfun' },
    { label: 'Nemotron (NVIDIA)', value: 'nemotron' }
  ],
  deepseek: [
    { label: 'DeepSeek Chat', value: 'deepeek-chat' }
  ],
  nvidia: [
    { label: 'Minimax M2.1', value: 'minimax' },
    { label: 'DeepSeek V3.2', value: 'deepseek-3.2' },
    { label: 'GLM 4.7', value: 'glm' }
  ],
  z_ai: [
    { label: 'GLM 4.7 Flash', value: 'glm-4.7' }
  ]
}

// 响应式数据
const sessions = ref<Session[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchKeyword = ref('')
const statusFilter = ref('')
const createDialogVisible = ref(false)
const creating = ref(false)
const deleteLoading = ref(false)
const selectedSessions = ref<string[]>([])
const createForm = ref<CreateSessionParams>({
  description: '',
  workspace: '',
  provider: undefined,
  model: undefined
})

// Workspace autocomplete suggestions
const workspaceAllSuggestions = ref<string[]>([])

// Workspace picker dialog
const workspacePickerVisible = ref(false)

// 计算属性
const isLoggedIn = computed(() => userStore.isLoggedIn)

// 根据选择的 provider 获取可用的 models
const availableModels = computed(() => {
  const provider = createForm.value.provider
  if (!provider) {
    return []
  }
  const key = provider.replace('-', '_')
  return LLM_MODELS[key] || []
})

// 加载session列表
const loadSessions = async () => {
  if (!isLoggedIn.value) {
    return
  }

  try {
    loading.value = true
    const response = await sessionApi.getSessions({
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
      status: statusFilter.value || undefined,
      keyword: searchKeyword.value || undefined
    })
    sessions.value = response.sessions || []
    total.value = response.total || 0
  } catch (error: any) {
    console.error('加载会话列表失败:', error)
    ElMessage.error('加载会话列表失败')
  } finally {
    loading.value = false
  }
}

// 显示创建会话弹窗
const showCreateDialog = () => {
  createForm.value = {
    description: '',
    workspace: '',
    provider: undefined,
    model: undefined
  }
  extractWorkspaceSuggestions()
  createDialogVisible.value = true
}

// 从现有会话中提取工作空间路径建议
const extractWorkspaceSuggestions = () => {
  const workspaces = new Set<string>()
  
  sessions.value.forEach(session => {
    if (session.workspace && session.workspace.trim()) {
      workspaces.add(session.workspace.trim())
    }
  })
  
  try {
    const localWorkspaces = localStorage.getItem('recent_workspaces')
    if (localWorkspaces) {
      const parsed = JSON.parse(localWorkspaces)
      if (Array.isArray(parsed)) {
        parsed.forEach((ws: string) => {
          if (ws && ws.trim()) {
            workspaces.add(ws.trim())
          }
        })
      }
    }
  } catch (e) {
    console.warn('Failed to parse local workspaces:', e)
  }
  
  workspaceAllSuggestions.value = Array.from(workspaces).filter(ws => ws.length > 0)
}

// 打开工作空间选择器
const openWorkspacePicker = () => {
  workspacePickerVisible.value = true
}

// 从文件浏览器选择工作空间
const selectWorkspaceFromPicker = (file: FileItem) => {
  if (file.is_dir) {
    createForm.value.workspace = file.path
    workspacePickerVisible.value = false
    saveRecentWorkspace(file.path)
  } else {
    ElMessage.warning('请选择目录而不是文件')
  }
}

// 保存最近使用的工作空间
const saveRecentWorkspace = (workspace: string) => {
  try {
    const key = 'recent_workspaces'
    let recent: string[] = []
    const existing = localStorage.getItem(key)
    if (existing) {
      recent = JSON.parse(existing)
    }
    
    recent = recent.filter(ws => ws !== workspace)
    recent.unshift(workspace)
    
    if (recent.length > 10) {
      recent = recent.slice(0, 10)
    }
    
    localStorage.setItem(key, JSON.stringify(recent))
  } catch (e) {
    console.warn('Failed to save recent workspace:', e)
  }
}

// 处理创建会话
const handleCreate = async () => {
  if (!isLoggedIn.value) {
    return
  }

  try {
    creating.value = true
    const response = await sessionApi.createSession({
      description: createForm.value.description || undefined,
      workspace: createForm.value.workspace || undefined,
      provider: createForm.value.provider || undefined,
      model: createForm.value.model || undefined
    })
    
    ElMessage.success('会话创建成功')
    createDialogVisible.value = false
    
    // 跳转到新创建的会话
    router.push(`/chat/${response.session_id}`)
  } catch (error: any) {
    console.error('创建会话失败:', error)
    ElMessage.error('创建会话失败: ' + (error.message || '未知错误'))
  } finally {
    creating.value = false
  }
}

// 处理搜索
const handleSearch = (keyword: string) => {
  searchKeyword.value = keyword
  currentPage.value = 1
  loadSessions()
}

// 处理状态筛选
const handleStatusFilterChange = (status: string) => {
  statusFilter.value = status
  currentPage.value = 1
  loadSessions()
}

// 处理页码变化
const handlePageChange = (page: number) => {
  currentPage.value = page
  loadSessions()
}

// 处理每页条数变化
const handleSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  loadSessions()
}

// 处理选择变化
const handleSelect = (sessionId: string) => {
  if (!selectedSessions.value.includes(sessionId)) {
    selectedSessions.value.push(sessionId)
  }
}

const handleDeselect = (sessionId: string) => {
  selectedSessions.value = selectedSessions.value.filter(id => id !== sessionId)
}

// 删除单个会话
const handleDelete = async (session: Session) => {
  // 确认框已在 SessionCard 组件中弹出，这里直接执行删除
  deleteLoading.value = true
  try {
    await sessionApi.deleteSession(session.session_id)
    ElMessage.success('删除成功')
    selectedSessions.value = selectedSessions.value.filter(id => id !== session.session_id)
    // 立即从本地列表移除已删除的session，避免用户点击到已删除的项
    sessions.value = sessions.value.filter(s => s.session_id !== session.session_id)
    total.value = Math.max(0, total.value - 1)
    // 如果当前页没有数据了且不是第一页，跳转到前一页
    if (sessions.value.length === 0 && currentPage.value > 1) {
      currentPage.value = 1
      loadSessions()
    } else {
      // 保持当前页，只更新总数
      // 如果需要，可以在这里调用 loadSessions() 从服务器重新获取，确保数据一致性
      // 但为了快速响应，先更新本地数据，稍后异步刷新
      setTimeout(loadSessions, 500) // 延迟500ms刷新，避免与用户操作冲突
    }
  } catch (error: any) {
    console.error('删除会话失败:', error)
    ElMessage.error('删除失败')
  } finally {
    deleteLoading.value = false
  }
}

// 批量删除会话
const handleBatchDelete = async () => {
  if (selectedSessions.value.length === 0) return
  
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedSessions.value.length} 个会话吗？此操作不可恢复。`,
      '确认批量删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    deleteLoading.value = true
    await sessionApi.deleteSessions(selectedSessions.value)
    ElMessage.success(`成功删除 ${selectedSessions.value.length} 个会话`)
    // 立即从本地列表移除已删除的sessions
    const deletedIds = new Set(selectedSessions.value)
    sessions.value = sessions.value.filter(s => !deletedIds.has(s.session_id))
    const removedCount = selectedSessions.value.length
    total.value = Math.max(0, total.value - removedCount)
    selectedSessions.value = []
    // 如果当前页没有数据了且不是第一页，跳转到前一页
    if (sessions.value.length === 0 && currentPage.value > 1) {
      currentPage.value = 1
      loadSessions()
    } else {
      // 延迟刷新列表
      setTimeout(loadSessions, 500)
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('批量删除会话失败:', error)
      ElMessage.error('批量删除失败')
    }
  } finally {
    deleteLoading.value = false
  }
}

// 处理工作空间选择
const handleWorkspaceSelect = (file: FileItem) => {
  selectWorkspaceFromPicker(file)
}

const handleWorkspaceConfirm = (path: string) => {
  createForm.value.workspace = path
  saveRecentWorkspace(path)
}

// 监听筛选条件变化
watch([statusFilter], () => {
  currentPage.value = 1
  loadSessions()
})

// 组件挂载时执行
onMounted(async () => {
  await userStore.init()
  if (!isLoggedIn.value) {
    router.push('/auth')
    return
  }
  loadSessions()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 页面标题栏 -->
    <div class="sticky top-0 z-10 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <div class="flex items-center gap-3">
            <el-icon class="text-blue-600 text-xl"><ChatRound /></el-icon>
            <h1 class="text-xl font-bold text-gray-900">会话管理</h1>
          </div>
          <div class="flex items-center gap-4">
            <div class="text-sm text-gray-500">
              共 {{ total }} 个会话
            </div>
            <el-button
              type="primary"
              :icon="Plus"
              @click="showCreateDialog"
            >
              创建会话
            </el-button>
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
          :status-filter="statusFilter"
          :is-logged-in="isLoggedIn"
          @update:search-keyword="handleSearch"
          @update:status-filter="handleStatusFilterChange"
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
        @page-change="handlePageChange"
        @size-change="handleSizeChange"
        @select="handleSelect"
        @deselect="handleDeselect"
        @delete="handleDelete"
        @batch-delete="handleBatchDelete"
      />
    </div>
  </div>

  <!-- 创建会话弹窗 -->
  <CreateSessionDialog
    :visible="createDialogVisible"
    :form-data="createForm"
    :workspace-suggestions="workspaceAllSuggestions"
    :available-models="availableModels"
    :creating="creating"
    @update:visible="createDialogVisible = $event"
    @update:form-data="createForm = $event"
    @create="handleCreate"
    @open-workspace-picker="openWorkspacePicker"
  />

  <!-- 工作空间选择器 -->
  <WorkspacePicker
    :visible="workspacePickerVisible"
    :initial-path="createForm.workspace || '/home/ubuntu'"
    @update:visible="workspacePickerVisible = $event"
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
