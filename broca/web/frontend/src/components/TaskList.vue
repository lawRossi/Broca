<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '@/api/task'
import { TaskStatus, TaskPriority } from '@/api/task'
import { Loading, Document, Edit, Delete, Check, Clock, Warning, User, Link, MoreFilled } from '@element-plus/icons-vue'

interface Props {
  tasks: Task[]
  loading: boolean
  selectedTasks: string[]
}

interface Emits {
  (e: 'select', taskId: string): void
  (e: 'deselect', taskId: string): void
  (e: 'view', task: Task): void
  (e: 'edit', task: Task): void
  (e: 'delete', task: Task): void
  (e: 'update-status', task: Task, status: TaskStatus): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const isAllSelected = computed(() => {
  return props.tasks.length > 0 && props.selectedTasks.length === props.tasks.length
})

const isIndeterminate = computed(() => {
  return props.selectedTasks.length > 0 && props.selectedTasks.length < props.tasks.length
})

const handleSelectAll = () => {
  if (isAllSelected.value) {
    props.tasks.forEach((task) => {
      if (props.selectedTasks.includes(task.task_id)) {
        emit('deselect', task.task_id)
      }
    })
  } else {
    props.tasks.forEach((task) => {
      if (!props.selectedTasks.includes(task.task_id)) {
        emit('select', task.task_id)
      }
    })
  }
}

const handleTaskSelect = (taskId: string) => emit('select', taskId)
const handleTaskDeselect = (taskId: string) => emit('deselect', taskId)
const handleView = (task: Task) => emit('view', task)
const handleEdit = (task: Task) => emit('edit', task)
const handleDelete = (task: Task) => emit('delete', task)
const handleUpdateStatus = (task: Task, status: TaskStatus) => emit('update-status', task, status)

const getStatusType = (status: TaskStatus): string => {
  switch (status) {
    case TaskStatus.PENDING:
      return 'info'
    case TaskStatus.IN_PROGRESS:
      return 'primary'
    case TaskStatus.BLOCKED:
      return 'warning'
    case TaskStatus.COMPLETED:
      return 'success'
    default:
      return 'info'
  }
}

const getStatusText = (status: TaskStatus): string => {
  switch (status) {
    case TaskStatus.PENDING:
      return '待处理'
    case TaskStatus.IN_PROGRESS:
      return '进行中'
    case TaskStatus.BLOCKED:
      return '已阻塞'
    case TaskStatus.COMPLETED:
      return '已完成'
    default:
      return '未知'
  }
}

const getStatusIcon = (status: TaskStatus) => {
  switch (status) {
    case TaskStatus.PENDING:
      return Clock
    case TaskStatus.IN_PROGRESS:
      return Loading
    case TaskStatus.BLOCKED:
      return Warning
    case TaskStatus.COMPLETED:
      return Check
    default:
      return Clock
  }
}

const getPriorityType = (priority: TaskPriority): string => {
  switch (priority) {
    case TaskPriority.LOW:
      return 'info'
    case TaskPriority.MEDIUM:
      return 'warning'
    case TaskPriority.HIGH:
      return 'danger'
    default:
      return 'info'
  }
}

const getPriorityText = (priority: TaskPriority): string => {
  switch (priority) {
    case TaskPriority.LOW:
      return '低'
    case TaskPriority.MEDIUM:
      return '中'
    case TaskPriority.HIGH:
      return '高'
    default:
      return '未知'
  }
}

const formatDate = (dateString: string): string => {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  if (diffHours < 24) return `${diffHours}小时前`
  if (diffDays < 7) return `${diffDays}天前`

  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

const getDescriptionPreview = (description?: string): string => {
  if (!description) return ''
  return description.length > 100 ? description.substring(0, 100) + '...' : description
}

const getStatusOptions = (currentStatus: TaskStatus) => {
  const allStatuses = [
    { value: TaskStatus.PENDING, label: '待处理', icon: Clock },
    { value: TaskStatus.IN_PROGRESS, label: '进行中', icon: Loading },
    { value: TaskStatus.BLOCKED, label: '已阻塞', icon: Warning },
    { value: TaskStatus.COMPLETED, label: '已完成', icon: Check },
  ]

  return allStatuses.filter((option) => option.value !== currentStatus)
}
</script>

<template>
  <div class="task-list">
    <!-- 批量操作栏 -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 translate-y-4"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-4"
    >
      <div
        v-if="selectedTasks.length > 0"
        class="fixed bottom-4 left-4 right-4 md:left-auto md:right-4 md:w-auto z-50 md:z-40"
      >
        <div
          class="mx-auto md:mx-0 bg-gray-900 text-white rounded-xl shadow-xl px-4 py-3 flex items-center justify-between md:justify-start gap-3 md:gap-4 max-w-md"
        >
          <div class="flex items-center gap-2">
            <el-checkbox
              :model-value="isAllSelected"
              :indeterminate="isIndeterminate"
              @change="handleSelectAll"
              class="task-checkbox"
            />
            <span class="text-sm font-medium">已选 {{ selectedTasks.length }} 项</span>
          </div>
          <span class="text-xs text-gray-400 hidden sm:inline">批量操作暂未开放</span>
        </div>
      </div>
    </Transition>

    <!-- 加载状态 -->
    <div v-if="loading" class="flex flex-col items-center justify-center py-16">
      <div class="relative">
        <el-icon class="is-loading text-primary-500" size="32">
          <Loading />
        </el-icon>
      </div>
      <span class="mt-3 text-gray-500 text-sm">加载中...</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="tasks.length === 0" class="flex flex-col items-center justify-center py-16 text-gray-400">
      <div class="w-20 h-20 mb-4 rounded-full bg-gray-100 flex items-center justify-center">
        <el-icon size="36" class="text-gray-300">
          <Document />
        </el-icon>
      </div>
      <p class="text-gray-500 font-medium">暂无任务</p>
      <p class="text-sm mt-1 text-gray-400">可通过Agent的task工具创建</p>
    </div>

    <!-- 任务列表 -->
    <div v-else class="space-y-3">
      <div
        v-for="task in tasks"
        :key="task.task_id"
        class="task-card group bg-white rounded-xl border border-gray-100 p-4 cursor-pointer transition-all duration-200 hover:border-gray-200 hover:shadow-md"
        :class="{
          'ring-2 ring-primary-500 border-primary-500 bg-primary-50/30': selectedTasks.includes(task.task_id),
          'hover:-translate-y-0.5': !selectedTasks.includes(task.task_id),
        }"
        @click="handleView(task)"
      >
        <div class="flex gap-3">
          <!-- 选择框 -->
          <div class="pt-1" @click.stop>
            <el-checkbox
              :model-value="selectedTasks.includes(task.task_id)"
              class="task-checkbox"
              @change="(val: boolean) => (val ? handleTaskSelect(task.task_id) : handleTaskDeselect(task.task_id))"
            />
          </div>

          <!-- 主内容区 -->
          <div class="flex-1 min-w-0">
            <!-- 标题行 -->
            <div class="flex items-start justify-between gap-2 mb-2">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <h3 class="text-base font-semibold text-gray-900 truncate">
                  {{ task.name }}
                </h3>
              </div>

              <!-- 移动端：显示更多菜单 -->
              <el-dropdown
                trigger="click"
                @command="
                  (cmd: string) => {
                    if (cmd === 'edit') handleEdit(task)
                    else if (cmd === 'delete') handleDelete(task)
                    else if (cmd === 'status') {
                    }
                  }
                "
                @click.stop
                class="md:hidden"
              >
                <el-button size="small" text class="opacity-0 group-hover:opacity-100 transition-opacity">
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="status">
                      <el-icon class="mr-1"><Link /></el-icon>
                      修改状态
                    </el-dropdown-item>
                    <el-dropdown-item command="edit">
                      <el-icon class="mr-1"><Edit /></el-icon>
                      编辑
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" divided>
                      <el-icon class="mr-1 text-red-500"><Delete /></el-icon>
                      <span class="text-red-500">删除</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <!-- 标签行 -->
            <div class="flex items-center gap-2 mb-3 flex-wrap">
              <el-tag :type="getStatusType(task.status)" size="small" effect="light" round class="task-tag">
                <el-icon class="mr-0.5" size="10">
                  <component :is="getStatusIcon(task.status)" />
                </el-icon>
                {{ getStatusText(task.status) }}
              </el-tag>
              <el-tag :type="getPriorityType(task.priority)" size="small" effect="light" round class="task-tag">
                {{ getPriorityText(task.priority) }}
              </el-tag>
            </div>

            <!-- 描述 -->
            <div v-if="task.description" class="text-sm text-gray-500 mb-3 line-clamp-2">
              {{ getDescriptionPreview(task.description) }}
            </div>

            <!-- 信息行 -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3 text-xs text-gray-400">
                <!-- 分配者 -->
                <div v-if="task.assignee" class="flex items-center gap-1">
                  <el-icon size="12">
                    <User />
                  </el-icon>
                  <span class="truncate max-w-[80px]">{{ task.assignee }}</span>
                </div>

                <!-- 依赖数量 -->
                <div v-if="task.dependencies && task.dependencies.length > 0" class="flex items-center gap-1">
                  <el-icon size="12">
                    <Link />
                  </el-icon>
                  <span>{{ task.dependencies.length }}</span>
                </div>

                <!-- 子任务 -->
                <div v-if="task.parent_id" class="flex items-center gap-1">
                  <span class="text-gray-300">↳</span>
                  <span>子任务</span>
                </div>
              </div>

              <div class="text-xs text-gray-400">
                {{ formatDate(task.updated_at) }}
              </div>
            </div>
          </div>

          <!-- 桌面端操作按钮 -->
          <div class="hidden md:flex flex-col items-center gap-2 ml-2" @click.stop>
            <!-- 状态切换 -->
            <el-dropdown @command="(status: TaskStatus) => handleUpdateStatus(task, status)">
              <el-button size="small" type="primary" circle class="task-action-btn">
                <el-icon size="12">
                  <component :is="getStatusIcon(task.status)" />
                </el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="option in getStatusOptions(task.status)"
                    :key="option.value"
                    :command="option.value"
                  >
                    <el-icon class="mr-2">
                      <component :is="option.icon" />
                    </el-icon>
                    {{ option.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <!-- 编辑按钮 -->
            <el-button size="small" type="default" circle class="task-action-btn" @click="handleEdit(task)">
              <el-icon size="12">
                <Edit />
              </el-icon>
            </el-button>

            <!-- 删除按钮 -->
            <el-button
              size="small"
              type="default"
              circle
              class="task-action-btn hover:text-red-500"
              @click="handleDelete(task)"
            >
              <el-icon size="12">
                <Delete />
              </el-icon>
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-list {
  width: 100%;
}

.task-card {
  contain: layout style;
}

.task-card:hover .task-action-btn {
  opacity: 1;
}

.task-action-btn {
  opacity: 0.6;
  transition: all 0.2s ease;
}

.task-action-btn:hover {
  opacity: 1;
  transform: scale(1.1);
}

.task-tag {
  font-size: 11px;
  padding: 0 8px;
  height: 22px;
  line-height: 20px;
}

.task-checkbox :deep(.el-checkbox__inner) {
  border-radius: 4px;
}

@media (max-width: 640px) {
  .task-card {
    padding: 12px;
    border-radius: 12px;
  }

  .task-card h3 {
    font-size: 15px;
  }

  .task-tag {
    font-size: 10px;
    padding: 0 6px;
    height: 18px;
    line-height: 16px;
  }

  .task-card .el-button--small {
    padding: 6px;
    height: 28px;
    width: 28px;
  }

  .task-card .el-button--small .el-icon {
    font-size: 12px;
  }
}

@media (max-width: 480px) {
  .task-list {
    margin: 0 -12px;
    padding: 0 12px;
  }
}
</style>
