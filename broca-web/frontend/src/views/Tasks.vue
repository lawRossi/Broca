<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores'
import { useTaskStore } from '@/stores'
import type { Task, TaskStatus } from '@/api/task'
import { TaskStatus as TaskStatusEnum, TaskPriority as TaskPriorityEnum } from '@/api/task'
import { Document, Refresh, Plus, User } from '@element-plus/icons-vue'

// 导入组件
import TaskList from '@/components/TaskList.vue'
import TaskDetail from '@/components/TaskDetail.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const taskStore = useTaskStore()

// 计算属性（从store获取）
const tasks = computed(() => taskStore.filteredTasks)
const loading = computed(() => taskStore.loading)
const total = computed(() => taskStore.total)
const currentPage = computed(() => taskStore.currentPage)
const pageSize = computed(() => taskStore.pageSize)
const searchKeyword = computed(() => taskStore.searchKeyword)
// 搜索框使用本地 ref，避免每次按键都触发 API 搜索
const localSearchKeyword = ref('')

// 同步 store 的 searchKeyword 到本地 ref（如路由恢复时）
watch(searchKeyword, (val) => {
  localSearchKeyword.value = val
})
const statusFilter = computed(() => taskStore.statusFilter)
const priorityFilter = computed(() => taskStore.priorityFilter)
const assigneeFilter = computed(() => taskStore.assigneeFilter)
const sessionFilter = computed(() => taskStore.sessionFilter)
const parentFilter = computed(() => taskStore.parentFilter)
const selectedTasks = computed(() => taskStore.selectedTasks)
const detailDrawerVisible = computed(() => taskStore.detailDrawerVisible)
const selectedTaskId = computed(() => taskStore.selectedTaskId)

// 计算属性：状态和优先级选项
const statusOptions = computed(() => [
  { label: '全部状态', value: '' },
  { label: '待处理', value: TaskStatusEnum.PENDING },
  { label: '进行中', value: TaskStatusEnum.IN_PROGRESS },
  { label: '已阻塞', value: TaskStatusEnum.BLOCKED },
  { label: '已完成', value: TaskStatusEnum.COMPLETED },
])

const priorityOptions = computed(() => [
  { label: '全部优先级', value: '' },
  { label: '低', value: TaskPriorityEnum.LOW },
  { label: '中', value: TaskPriorityEnum.MEDIUM },
  { label: '高', value: TaskPriorityEnum.HIGH },
])

// 计算属性：是否已登录
const isLoggedIn = computed(() => userStore.isLoggedIn)

// 搜索
const handleSearch = () => {
  taskStore.setSearchKeyword(localSearchKeyword.value)
}
const handleClearSearch = () => {
  localSearchKeyword.value = ''
  taskStore.setSearchKeyword('')
}

// 状态筛选
const handleStatusFilterChange = (status: string) => {
  taskStore.setStatusFilter(status as any)
}

// 优先级筛选
const handlePriorityFilterChange = (priority: string) => {
  taskStore.setPriorityFilter(priority as any)
}

// 分配对象筛选
const handleAssigneeFilterChange = (assignee: string) => {
  taskStore.setAssigneeFilter(assignee)
}

// 清除 session 筛选
const clearSessionFilter = () => {
  taskStore.setSessionFilter('')
  router.replace('/tasks')
}

// 清除 parent 筛选
const clearParentFilter = () => {
  taskStore.setParentFilter('')
}

// 分页
const handlePageChange = (page: number) => {
  taskStore.setPage(page)
  taskStore.fetchTasks()
}

const handleSizeChange = (size: number) => {
  taskStore.setPageSize(size)
}

// 选择任务
const handleSelect = (taskId: string) => {
  taskStore.selectTask(taskId)
}

const handleDeselect = (taskId: string) => {
  taskStore.deselectTask(taskId)
}

// 查看详情
const handleView = (task: Task) => {
  taskStore.openDetail(task.task_id)
}

// 编辑任务
const handleEdit = (task: Task) => {
  // 打开详情页并进入编辑模式
  taskStore.openDetail(task.task_id)
}

// 删除任务
const handleDelete = async (task: Task) => {
  try {
    await taskStore.deleteTask(task.task_id)
  } catch (error: any) {
    console.error('删除任务失败:', error)
  }
}

// 更新状态
const handleUpdateStatus = async (task: Task, status: TaskStatus) => {
  try {
    await taskStore.updateTask(task.task_id, { status })
  } catch (error: any) {
    console.error('更新状态失败:', error)
  }
}

// 创建新任务
const handleCreateTask = async () => {
  try {
    const result = await ElMessageBox.prompt('请输入任务名称', '创建新任务', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPlaceholder: '任务名称',
      inputValidator: (value) => {
        if (!value || value.trim().length === 0) {
          return '任务名称不能为空'
        }
        return true
      },
    })

    const name = (result as any).value.trim()
    const description = await ElMessageBox.prompt('请输入任务描述', '任务描述', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPlaceholder: '任务描述',
      inputType: 'textarea',
      inputValidator: (value) => {
        if (!value || value.trim().length === 0) {
          return '任务描述不能为空'
        }
        return true
      },
    })

    await taskStore.createTask({
      name,
      description: (description as any).value.trim(),
      session_id: sessionFilter.value || undefined,
    })
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('创建任务失败:', error)
    }
  }
}

// 监听筛选条件变化
watch(
  [searchKeyword, statusFilter, priorityFilter, assigneeFilter, sessionFilter, parentFilter],
  () => {
    // 筛选条件变化时重新加载
    taskStore.fetchTasks()
  },
  { deep: true }
)

// 监听路由参数变化
watch(
  () => route.query.session_id,
  (newSessionId) => {
    taskStore.setSessionFilter((newSessionId as string) || '')
  },
  { immediate: true }
)

watch(
  () => route.query.parent_id,
  (newParentId) => {
    taskStore.setParentFilter((newParentId as string) || '')
  },
  { immediate: true }
)

// 组件挂载
onMounted(async () => {
  await userStore.init()
  if (!isLoggedIn.value) {
    router.push('/auth')
    return
  }

  // 从路由参数中获取 session_id 和 parent_id
  const sessionIdFromRoute = route.query.session_id as string
  const parentIdFromRoute = route.query.parent_id as string

  if (sessionIdFromRoute) {
    taskStore.setSessionFilter(sessionIdFromRoute)
  }

  if (parentIdFromRoute) {
    taskStore.setParentFilter(parentIdFromRoute)
  }

  await taskStore.fetchTasks()
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
              <Document />
            </el-icon>
            <h1 class="text-xl font-bold text-gray-900">任务管理</h1>
          </div>
          <div class="flex items-center gap-4">
            <div class="text-sm text-gray-500">共 {{ total }} 个任务</div>
            <el-button type="primary" :icon="Plus" @click="handleCreateTask"> 新建任务 </el-button>
            <el-button :loading="loading" :icon="Refresh" @click="taskStore.refresh()"> 刷新 </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
      <!-- 搜索和筛选栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-4 mb-6">
        <div class="flex flex-wrap gap-4 items-center">
          <!-- 搜索框 -->
          <el-input
            v-model="localSearchKeyword"
            placeholder="搜索任务名称、ID或描述"
            clearable
            style="width: 300px"
            @clear="handleClearSearch"
            @keyup.enter="handleSearch"
          >
            <template #prefix>
              <el-icon>
                <svg viewBox="0 0 24 24" width="16" height="16">
                  <path
                    fill="currentColor"
                    d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"
                  />
                </svg>
              </el-icon>
            </template>
          </el-input>

          <!-- 状态筛选 -->
          <el-select
            v-model="statusFilter"
            placeholder="任务状态"
            clearable
            style="width: 140px"
            @change="handleStatusFilterChange"
          >
            <el-option
              v-for="option in statusOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <!-- 优先级筛选 -->
          <el-select
            v-model="priorityFilter"
            placeholder="任务优先级"
            clearable
            style="width: 140px"
            @change="handlePriorityFilterChange"
          >
            <el-option
              v-for="option in priorityOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <!-- 分配对象筛选 -->
          <el-input
            v-model="assigneeFilter"
            placeholder="分配对象"
            clearable
            style="width: 140px"
            @clear="handleAssigneeFilterChange('')"
            @blur="handleAssigneeFilterChange(assigneeFilter)"
          >
            <template #prefix>
              <el-icon><User /></el-icon>
            </template>
          </el-input>

          <!-- Session 筛选提示 -->
          <el-tag v-if="sessionFilter" type="info" closable class="ml-2" @close="clearSessionFilter">
            会话: {{ sessionFilter.slice(0, 8) }}...
          </el-tag>

          <!-- Parent 筛选提示 -->
          <el-tag v-if="parentFilter" type="info" closable class="ml-2" @close="clearParentFilter">
            父任务: {{ parentFilter.slice(0, 8) }}...
          </el-tag>
        </div>
      </div>

      <!-- 任务列表 -->
      <TaskList
        :tasks="tasks"
        :loading="loading"
        :selected-tasks="selectedTasks"
        @select="handleSelect"
        @deselect="handleDeselect"
        @view="handleView"
        @edit="handleEdit"
        @delete="handleDelete"
        @update-status="handleUpdateStatus"
      />

      <!-- 分页器 -->
      <div v-if="!loading && total > 0" class="mt-4 bg-white rounded-lg shadow-sm border p-4">
        <el-pagination
          :current-page="currentPage"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          size="small"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <!-- 任务详情抽屉 -->
    <TaskDetail :visible="detailDrawerVisible" :task-id="selectedTaskId" @update:visible="taskStore.closeDetail()" />
  </div>
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

  .bg-white.rounded-lg.shadow-sm.border.p-4 {
    padding: 1rem;
  }

  .flex.flex-wrap.gap-4.items-center {
    gap: 0.75rem;
  }

  .el-input {
    width: 100% !important;
  }

  /* 筛选区域 */
  .flex.flex-wrap.gap-4.items-center .el-select {
    flex: 1 1 auto;
    min-width: 120px;
  }

  /* 批量操作栏 */
  .fixed.bottom-6.left-1\/2.transform.-translate-x-1\/2.z-50 {
    bottom: 20px;
    padding: 8px 12px;
    max-width: 95% !important;
  }

  .fixed.bottom-6.left-1\/2.transform.-translate-x-1\/2.z-50 .text-sm {
    font-size: 0.75rem;
  }
}
</style>
