<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores'
import { sessionApi, type Session, type CreateSessionParams } from '@/api/session'
import { ChatRound, Search, ArrowRight, Calendar, Timer, Plus, Delete, Loading } from '@element-plus/icons-vue'
import { formatBeijingTime } from '@/utils/time'

const router = useRouter()
const userStore = useUserStore()

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
  workspace: ''
})

// 计算属性：是否已登录
const isLoggedIn = computed(() => userStore.isLoggedIn)

// 计算属性：是否全选
const isAllSelected = computed(() => {
  return sessions.value.length > 0 && 
    selectedSessions.value.length === sessions.value.length
})

// 计算属性：是否部分选择
const isIndeterminate = computed(() => {
  return selectedSessions.value.length > 0 && 
    selectedSessions.value.length < sessions.value.length
})

// 计算属性：是否有选中项
const hasSelection = computed(() => selectedSessions.value.length > 0)

// 状态选项
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '进行中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '已暂停', value: 'paused' },
  { label: '错误', value: 'error' },
]

// 获取状态标签样式
const getStatusType = (status: string) => {
  const map: Record<string, string> = {
    active: 'success',
    completed: 'info',
    paused: 'warning',
    error: 'danger'
  }
  return map[status] || 'info'
}

// 获取状态显示文本
const getStatusLabel = (status: string) => {
  const map: Record<string, string> = {
    active: '进行中',
    completed: '已完成',
    paused: '已暂停',
    error: '错误'
  }
  return map[status] || status
}

// 使用工具函数

// 截断ID显示
const truncateId = (id: string, length: number = 8) => {
  if (!id) return ''
  if (id.length <= length * 2 + 3) return id
  return `${id.slice(0, length)}...${id.slice(-length)}`
}

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

// 跳转到聊天页面
const goToChat = (sessionId: string) => {
  router.push(`/chat/${sessionId}`)
}

// 显示创建会话弹窗
const showCreateDialog = () => {
  createForm.value = {
    description: '',
    workspace: ''
  }
  createDialogVisible.value = true
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
      workspace: createForm.value.workspace || undefined
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
const handleSearch = () => {
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

// 处理表格选择变化
const handleSelectionChange = (selection: Session[]) => {
  selectedSessions.value = selection.map(s => s.session_id)
}

// 全选/取消全选
const toggleSelectAll = () => {
  if (isAllSelected.value) {
    selectedSessions.value = []
  } else {
    selectedSessions.value = sessions.value.map(s => s.session_id)
  }
}

// 删除单个会话
const handleDelete = async (session: Session) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除会话 "${session.description || session.session_id}" 吗？此操作不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    deleteLoading.value = true
    await sessionApi.deleteSession(session.session_id)
    ElMessage.success('删除成功')
    selectedSessions.value = selectedSessions.value.filter(id => id !== session.session_id)
    loadSessions()
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('删除会话失败:', error)
      ElMessage.error('删除失败')
    }
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
    selectedSessions.value = []
    loadSessions()
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('批量删除会话失败:', error)
      ElMessage.error('批量删除失败')
    }
  } finally {
    deleteLoading.value = false
  }
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
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
      <!-- 搜索和筛选栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-4 mb-6">
        <div class="flex flex-col sm:flex-row gap-4">
          <!-- 搜索框 -->
          <div class="flex-1">
            <el-input
              v-model="searchKeyword"
              placeholder="搜索会话ID或描述..."
              clearable
              @keyup.enter="handleSearch"
              @clear="handleSearch"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
              <template #append>
                <el-button @click="handleSearch">搜索</el-button>
              </template>
            </el-input>
          </div>
          <!-- 状态筛选 -->
          <div class="sm:w-48">
            <el-select
              v-model="statusFilter"
              placeholder="状态筛选"
              clearable
              class="w-full"
            >
              <el-option
                v-for="opt in statusOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </div>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="bg-white rounded-lg shadow-sm border p-12">
        <div class="flex flex-col items-center justify-center">
          <el-icon class="text-4xl text-blue-500 animate-spin mb-4"><Loading /></el-icon>
          <p class="text-gray-600">加载中...</p>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="sessions.length === 0" class="bg-white rounded-lg shadow-sm border p-12">
        <div class="flex flex-col items-center justify-center text-center">
          <el-icon class="text-6xl text-gray-300 mb-4"><ChatRound /></el-icon>
          <h3 class="text-lg font-medium text-gray-900 mb-2">暂无会话</h3>
          <p class="text-gray-500 max-w-sm">
            {{ searchKeyword || statusFilter ? '没有找到符合条件的会话，请尝试调整搜索条件' : '还没有创建任何会话，开始一个新的对话吧' }}
          </p>
          <el-button 
            v-if="searchKeyword || statusFilter"
            type="primary" 
            class="mt-4"
            @click="searchKeyword = ''; statusFilter = ''; handleSearch()"
          >
            清除筛选条件
          </el-button>
        </div>
      </div>

      <!-- 会话列表 -->
      <div v-else class="space-y-4">
        <!-- 批量操作栏 -->
        <div class="bg-white rounded-lg shadow-sm border p-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-4">
              <el-checkbox
                :model-value="isAllSelected"
                :indeterminate="isIndeterminate"
                @change="toggleSelectAll"
              >
                全选
              </el-checkbox>
              <span class="text-sm text-gray-500">
                已选择 {{ selectedSessions.length }} 项
              </span>
            </div>
            <el-button
              v-if="hasSelection"
              type="danger"
              :loading="deleteLoading"
              @click="handleBatchDelete"
            >
              <el-icon class="mr-1"><Delete /></el-icon>
              批量删除 ({{ selectedSessions.length }})
            </el-button>
          </div>
        </div>

        <!-- PC端表格视图 -->
        <div class="hidden sm:block bg-white rounded-lg shadow-sm border overflow-hidden">
          <el-table 
            :data="sessions" 
            stripe 
            class="w-full"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="55" />
            <el-table-column label="会话ID" min-width="180">
              <template #default="{ row }">
                <div class="font-mono text-sm text-gray-600">
                  {{ truncateId(row.session_id, 12) }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="描述" min-width="200">
              <template #default="{ row }">
                <div class="text-gray-700 truncate">
                  {{ row.description || '-' }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)" size="small">
                  {{ getStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                <div class="text-sm text-gray-500 flex items-center gap-1">
                  <el-icon class="text-xs"><Calendar /></el-icon>
                  {{ formatBeijingTime(row.created_at) }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="结束时间" width="180">
              <template #default="{ row }">
                <div class="text-sm text-gray-500 flex items-center gap-1">
                  <el-icon class="text-xs"><Timer /></el-icon>
                  {{ row.finished_at ? formatBeijingTime(row.finished_at) : '-' }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" align="center" fixed="right">
              <template #default="{ row }">
                <div class="flex items-center justify-center gap-2">
                  <el-button
                    type="primary"
                    size="small"
                    @click="goToChat(row.session_id)"
                  >
                    进入
                  </el-button>
                  <el-button
                    type="danger"
                    size="small"
                    :loading="deleteLoading"
                    @click="handleDelete(row)"
                  >
                    <el-icon class="mr-1"><Delete /></el-icon>
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 移动端卡片视图 -->
        <div class="sm:hidden space-y-3">
          <!-- 移动端批量操作栏 -->
          <div v-if="hasSelection" class="bg-white rounded-lg shadow-sm border p-3 sticky top-20 z-10">
            <div class="flex items-center justify-between">
              <span class="text-sm text-gray-500">
                已选择 {{ selectedSessions.length }} 项
              </span>
              <el-button
                type="danger"
                size="small"
                :loading="deleteLoading"
                @click="handleBatchDelete"
              >
                <el-icon class="mr-1"><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </div>

          <div
            v-for="session in sessions"
            :key="session.session_id"
            class="bg-white rounded-lg shadow-sm border p-4"
            :class="{ 'ring-2 ring-blue-500': selectedSessions.includes(session.session_id) }"
          >
            <div class="flex items-start gap-3">
              <el-checkbox
                :model-value="selectedSessions.includes(session.session_id)"
                class="mt-1"
                @change="(val: boolean) => {
                  if (val) {
                    selectedSessions.push(session.session_id)
                  } else {
                    selectedSessions = selectedSessions.filter(id => id !== session.session_id)
                  }
                }"
              />
              <div 
                class="flex-1 min-w-0 active:bg-gray-50 transition-colors rounded"
                @click="goToChat(session.session_id)"
              >
                <div class="flex items-start justify-between mb-3">
                  <div class="flex-1 min-w-0">
                    <div class="font-mono text-sm text-gray-500 mb-1">
                      {{ truncateId(session.session_id, 10) }}
                    </div>
                    <div class="text-gray-900 font-medium truncate">
                      {{ session.description || '无描述' }}
                    </div>
                  </div>
                  <div class="ml-3 flex-shrink-0">
                    <el-tag :type="getStatusType(session.status)" size="small">
                      {{ getStatusLabel(session.status) }}
                    </el-tag>
                  </div>
                </div>
                <div class="flex items-center justify-between text-sm text-gray-500">
                  <div class="flex items-center gap-1">
                    <el-icon class="text-xs"><Calendar /></el-icon>
                    <span>{{ formatBeijingTime(session.created_at).split(' ')[0] }}</span>
                  </div>
                  <el-icon class="text-gray-400"><ArrowRight /></el-icon>
                </div>
              </div>
            </div>
            <!-- 移动端单个删除按钮 -->
            <div class="flex justify-end mt-3 pt-3 border-t">
              <el-button
                type="danger"
                size="small"
                :loading="deleteLoading"
                @click.stop="handleDelete(session)"
              >
                <el-icon class="mr-1"><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div class="bg-white rounded-lg shadow-sm border p-4">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="total"
            layout="total, sizes, prev, pager, next, jumper"
            :small="true"
            @size-change="handleSizeChange"
            @current-change="handlePageChange"
          />
        </div>
      </div>
    </div>
  </div>

  <!-- 创建会话弹窗 -->
  <el-dialog
    v-model="createDialogVisible"
    title="创建新会话"
    width="500px"
    :close-on-click-modal="false"
  >
    <el-form
      ref="createFormRef"
      :model="createForm"
      label-position="top"
    >
      <el-form-item label="描述（可选）">
        <el-input
          v-model="createForm.description"
          placeholder="输入会话描述..."
          clearable
        />
      </el-form-item>
      <el-form-item label="工作目录（可选）">
        <el-input
          v-model="createForm.workspace"
          placeholder="输入工作目录路径，留空则创建临时目录"
          clearable
        />
        <div class="text-xs text-gray-500 mt-1">
          如果不指定，系统将自动创建临时目录作为工作空间
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="creating"
          @click="handleCreate"
        >
          创建
        </el-button>
      </span>
    </template>
  </el-dialog>
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

/* 卡片点击效果 */
.smooth-transition {
  transition: all 0.2s ease;
}

.smooth-transition:active {
  transform: scale(0.98);
}
</style>
