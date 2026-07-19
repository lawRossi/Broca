<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '@/api/task'
import { TaskStatus, TaskPriority } from '@/api/task'
import {
  Loading,
  Document,
  Edit,
  Delete,
  Check,
  Clock,
  Warning,
  User,
  Link,
  MoreFilled,
  StarFilled,
} from '@element-plus/icons-vue'

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
  (e: 'toggle-star', task: Task): void
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
const handleToggleStar = (task: Task) => emit('toggle-star', task)

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

// 检查任务是否被标记为重要（模拟功能）
const isTaskStarred = (task: Task): boolean => {
  // 这里可以根据实际业务逻辑实现，暂时模拟
  return task.priority === TaskPriority.HIGH || task.status === TaskStatus.BLOCKED
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
          class="mx-auto md:mx-0 bg-gradient-to-r from-primary-600 to-primary-800 text-white rounded-xl shadow-2xl px-4 py-3 flex items-center justify-between md:justify-start gap-3 md:gap-4 max-w-md glass-dark"
        >
          <div class="flex items-center gap-2">
            <el-checkbox
              :model-value="isAllSelected"
              :indeterminate="isIndeterminate"
              class="task-checkbox"
              @change="handleSelectAll"
            />
            <span class="text-sm font-medium">已选 {{ selectedTasks.length }} 项</span>
          </div>
          <span class="text-xs text-primary-200 hidden sm:inline">批量操作暂未开放</span>
        </div>
      </div>
    </Transition>

    <!-- 加载状态 -->
    <div v-if="loading" class="flex flex-col items-center justify-center py-16">
      <div class="relative">
        <div
          class="w-16 h-16 rounded-full bg-gradient-to-r from-primary-100 to-primary-200 flex items-center justify-center animate-pulse"
        >
          <el-icon class="is-loading text-primary-600" size="28">
            <Loading />
          </el-icon>
        </div>
      </div>
      <span class="mt-4 text-gray-600 text-sm font-medium">加载任务中...</span>
      <span class="mt-1 text-gray-400 text-xs">请稍候</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="tasks.length === 0" class="flex flex-col items-center justify-center py-16">
      <div
        class="w-24 h-24 mb-6 rounded-full bg-gradient-to-br from-gray-50 to-gray-100 flex items-center justify-center shadow-inner"
      >
        <el-icon size="40" class="text-gray-400">
          <Document />
        </el-icon>
      </div>
      <p class="text-gray-700 font-semibold text-lg mb-2">暂无任务</p>
      <p class="text-gray-500 text-sm text-center max-w-xs">
        通过Agent的task工具创建任务<br />或点击右上角的"新建任务"按钮
      </p>
      <div class="mt-6 flex gap-3">
        <el-button type="primary" size="small" class="rounded-full px-4">
          <el-icon class="mr-1">
            <Edit />
          </el-icon>
          创建任务
        </el-button>
        <el-button type="default" size="small" class="rounded-full px-4"> 查看教程 </el-button>
      </div>
    </div>

    <!-- 任务列表 -->
    <div v-else class="space-y-4">
      <div
        v-for="task in tasks"
        :key="task.task_id"
        class="task-card group bg-white rounded-2xl border border-gray-100 p-5 cursor-pointer transition-all duration-300 hover:shadow-lg hover-lift"
        :class="{
          'ring-2 ring-primary-500 border-primary-500 bg-gradient-to-r from-primary-50/50 to-primary-50/20':
            selectedTasks.includes(task.task_id),
          'hover:border-primary-200': !selectedTasks.includes(task.task_id),
        }"
        @click="handleView(task)"
      >
        <div class="flex gap-4">
          <!-- 选择框和重要标记 -->
          <div class="flex flex-col items-center gap-3 pt-1" @click.stop>
            <el-checkbox
              :model-value="selectedTasks.includes(task.task_id)"
              class="task-checkbox"
              @change="(val: boolean) => (val ? handleTaskSelect(task.task_id) : handleTaskDeselect(task.task_id))"
            />

            <!-- 重要标记 -->
            <el-button
              v-if="isTaskStarred(task)"
              size="small"
              text
              class="!p-0 !h-6 !w-6"
              @click.stop="handleToggleStar(task)"
            >
              <el-icon class="text-amber-500 hover:text-amber-600 transition-colors">
                <StarFilled />
              </el-icon>
            </el-button>
          </div>

          <!-- 主内容区 -->
          <div class="flex-1 min-w-0">
            <!-- 标题行 -->
            <div class="flex items-start justify-between gap-3 mb-3">
              <div class="flex items-start gap-3 min-w-0 flex-1">
                <!-- 状态指示器 -->
                <div class="flex-shrink-0 mt-1">
                  <div
                    class="w-3 h-3 rounded-full"
                    :class="{
                      'bg-blue-500': task.status === TaskStatus.PENDING,
                      'bg-primary-500': task.status === TaskStatus.IN_PROGRESS,
                      'bg-amber-500': task.status === TaskStatus.BLOCKED,
                      'bg-green-500': task.status === TaskStatus.COMPLETED,
                    }"
                  />
                </div>

                <div class="min-w-0 flex-1">
                  <h3 class="text-lg font-semibold text-gray-900 truncate mb-1">
                    {{ task.name }}
                  </h3>

                  <!-- 标签行 -->
                  <div class="flex items-center gap-2 mb-3 flex-wrap">
                    <el-tag
                      :type="getStatusType(task.status)"
                      size="small"
                      effect="plain"
                      round
                      class="task-tag border-0 font-medium"
                    >
                      <el-icon class="mr-1" size="12">
                        <component :is="getStatusIcon(task.status)" />
                      </el-icon>
                      {{ getStatusText(task.status) }}
                    </el-tag>
                    <el-tag
                      :type="getPriorityType(task.priority)"
                      size="small"
                      effect="plain"
                      round
                      class="task-tag border-0 font-medium"
                    >
                      {{ getPriorityText(task.priority) }}
                    </el-tag>

                    <!-- 紧急标记 -->
                    <span
                      v-if="task.priority === TaskPriority.HIGH"
                      class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800"
                    >
                      <el-icon size="10" class="mr-1"><Warning /></el-icon>
                      紧急
                    </span>
                  </div>
                </div>
              </div>

              <!-- 移动端：显示更多菜单 -->
              <el-dropdown
                trigger="click"
                class="md:hidden"
                @command="
                  (cmd: string) => {
                    if (cmd === 'edit') handleEdit(task)
                    else if (cmd === 'delete') handleDelete(task)
                    else if (cmd === 'status') {
                    }
                  }
                "
                @click.stop
              >
                <el-button size="small" text class="opacity-70 hover:opacity-100 transition-opacity">
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="status">
                      <el-icon class="mr-2">
                        <Link />
                      </el-icon>
                      修改状态
                    </el-dropdown-item>
                    <el-dropdown-item command="edit">
                      <el-icon class="mr-2">
                        <Edit />
                      </el-icon>
                      编辑
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" divided>
                      <el-icon class="mr-2 text-red-500">
                        <Delete />
                      </el-icon>
                      <span class="text-red-500">删除</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>

            <!-- 描述 -->
            <div v-if="task.description" class="text-sm text-gray-600 mb-4 line-clamp-2 leading-relaxed">
              {{ getDescriptionPreview(task.description) }}
            </div>

            <!-- 信息行 -->
            <div class="flex items-center justify-between pt-3 border-t border-gray-100">
              <div class="flex items-center gap-4 text-xs text-gray-500">
                <!-- 分配者 -->
                <div v-if="task.assignee" class="flex items-center gap-1.5">
                  <div class="w-6 h-6 rounded-full bg-primary-100 flex items-center justify-center">
                    <el-icon size="10" class="text-primary-600">
                      <User />
                    </el-icon>
                  </div>
                  <span class="font-medium truncate max-w-[100px]">{{ task.assignee }}</span>
                </div>

                <!-- 依赖数量 -->
                <div v-if="task.dependencies && task.dependencies.length > 0" class="flex items-center gap-1.5">
                  <div class="w-6 h-6 rounded-full bg-purple-100 flex items-center justify-center">
                    <el-icon size="10" class="text-purple-600">
                      <Link />
                    </el-icon>
                  </div>
                  <span class="font-medium">{{ task.dependencies.length }} 个依赖</span>
                </div>

                <!-- 子任务 -->
                <div v-if="task.parent_id" class="flex items-center gap-1.5">
                  <div class="w-6 h-6 rounded-full bg-green-100 flex items-center justify-center">
                    <span class="text-green-600 text-xs">↳</span>
                  </div>
                  <span class="font-medium">子任务</span>
                </div>
              </div>

              <div class="text-xs text-gray-500 font-medium">
                {{ formatDate(task.updated_at) }}
              </div>
            </div>
          </div>

          <!-- 桌面端操作按钮 -->
          <div class="hidden md:flex flex-col items-center gap-3 ml-2" @click.stop>
            <!-- 状态切换 -->
            <el-dropdown @command="(status: TaskStatus) => handleUpdateStatus(task, status)">
              <el-button size="small" type="primary" circle class="task-action-btn hover-scale !w-10 !h-10 !shadow-md">
                <el-icon size="16">
                  <component :is="getStatusIcon(task.status)" />
                </el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="option in getStatusOptions(task.status)"
                    :key="option.value"
                    :command="option.value"
                    class="!px-4 !py-2"
                  >
                    <el-icon class="mr-3">
                      <component :is="option.icon" />
                    </el-icon>
                    {{ option.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <!-- 编辑按钮 -->
            <el-button
              size="small"
              type="default"
              circle
              class="task-action-btn hover-scale !w-10 !h-10 !shadow-sm hover:!border-primary-300"
              @click="handleEdit(task)"
            >
              <el-icon size="16" class="text-gray-600">
                <Edit />
              </el-icon>
            </el-button>

            <!-- 删除按钮 -->
            <el-button
              size="small"
              type="default"
              circle
              class="task-action-btn hover-scale !w-10 !h-10 !shadow-sm hover:!border-red-300 hover:!text-red-500"
              @click="handleDelete(task)"
            >
              <el-icon size="16" class="text-gray-600">
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
  position: relative;
  overflow: hidden;
}

.task-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(14, 165, 233, 0.1), transparent);
}

.task-card:hover .task-action-btn {
  opacity: 1;
}

.task-action-btn {
  opacity: 0.8;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid transparent;
}

.task-action-btn:hover {
  opacity: 1;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.15);
}

.task-tag {
  font-size: 12px;
  padding: 0 10px;
  height: 24px;
  line-height: 22px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.task-checkbox :deep(.el-checkbox__inner) {
  border-radius: 6px;
  border-width: 2px;
  width: 18px;
  height: 18px;
}

.task-checkbox :deep(.el-checkbox__inner::after) {
  border-width: 2px;
  height: 9px;
  left: 5px;
  top: 1px;
  width: 5px;
}

/* 移动端优化 */
@media (max-width: 768px) {
  .task-card {
    padding: 16px;
    border-radius: 16px;
    margin: 0 -8px;
  }

  .task-card h3 {
    font-size: 16px;
    line-height: 1.4;
  }

  .task-tag {
    font-size: 11px;
    padding: 0 8px;
    height: 22px;
    line-height: 20px;
  }

  .task-card .el-button--small {
    padding: 8px;
    height: 32px;
    width: 32px;
  }

  .task-card .el-button--small .el-icon {
    font-size: 14px;
  }
}

@media (max-width: 640px) {
  .task-card {
    padding: 14px;
    border-radius: 14px;
  }

  .task-card h3 {
    font-size: 15px;
  }

  .task-tag {
    font-size: 10px;
    padding: 0 7px;
    height: 20px;
    line-height: 18px;
  }
}

@media (max-width: 480px) {
  .task-card {
    padding: 12px;
    border-radius: 12px;
  }

  .task-card h3 {
    font-size: 14px;
  }

  .task-tag {
    font-size: 9px;
    padding: 0 6px;
    height: 18px;
    line-height: 16px;
  }

  .task-list {
    margin: 0 -4px;
    padding: 0 4px;
  }
}

/* 触摸设备优化 */
@media (hover: none) and (pointer: coarse) {
  .task-card {
    -webkit-tap-highlight-color: transparent;
  }

  .task-action-btn {
    opacity: 1;
    min-height: 44px;
    min-width: 44px;
  }

  .task-checkbox :deep(.el-checkbox__inner) {
    width: 20px;
    height: 20px;
  }
}
</style>
