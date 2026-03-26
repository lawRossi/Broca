<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { TaskStatus, TaskPriority } from '@/api/task'
import { TaskStatus as TaskStatusEnum, TaskPriority as TaskPriorityEnum } from '@/api/task'
import { useTaskStore } from '@/stores'
import { useUserStore } from '@/stores'
import { Loading, Check, Clock, Warning, User, Document, Link, Paperclip, Message, Edit } from '@element-plus/icons-vue'

interface Props {
  visible: boolean
  taskId?: string
}

interface Emits {
  (e: 'update:visible', visible: boolean): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const taskStore = useTaskStore()
const userStore = useUserStore()

// 评论相关
const newComment = ref('')
const submittingComment = ref(false)

// 编辑相关
const editing = ref(false)
const editForm = ref({
  name: '',
  description: '',
  details: '',
  acceptance_criteria: [] as string[],
  context_files: [] as string[],
  context_links: [] as string[],
  context_notes: '',
  report: '',
})

// 计算属性
const task = computed(() => taskStore.taskDetail?.task)
const comments = computed(() => taskStore.taskDetail?.comments || [])
const children = computed(() => taskStore.taskDetail?.children || [])
const loading = computed(() => taskStore.detailLoading)

const statusOptions = computed(() => [
  { value: TaskStatusEnum.PENDING, label: '待处理', icon: Clock, type: 'info' },
  { value: TaskStatusEnum.IN_PROGRESS, label: '进行中', icon: Loading, type: 'primary' },
  { value: TaskStatusEnum.BLOCKED, label: '已阻塞', icon: Warning, type: 'warning' },
  { value: TaskStatusEnum.COMPLETED, label: '已完成', icon: Check, type: 'success' },
])

const priorityOptions = computed(() => [
  { value: TaskPriorityEnum.LOW, label: '低', type: 'info' },
  { value: TaskPriorityEnum.MEDIUM, label: '中', type: 'warning' },
  { value: TaskPriorityEnum.HIGH, label: '高', type: 'danger' },
])

// 方法
const handleClose = () => {
  emit('update:visible', false)
  editing.value = false
}

const handleUpdateStatus = async (status: TaskStatus) => {
  if (!task.value) return
  
  try {
    await taskStore.updateTask(task.value.task_id, { status })
    ElMessage.success('状态更新成功')
  } catch (error) {
    console.error('更新状态失败:', error)
  }
}

const handleUpdatePriority = async (priority: TaskPriority) => {
  if (!task.value) return
  
  try {
    await taskStore.updateTask(task.value.task_id, { priority })
    ElMessage.success('优先级更新成功')
  } catch (error) {
    console.error('更新优先级失败:', error)
  }
}

const handleUpdateAssignee = async (assignee: string) => {
  if (!task.value) return
  
  try {
    await taskStore.updateTask(task.value.task_id, { assignee })
    ElMessage.success('分配对象更新成功')
  } catch (error) {
    console.error('更新分配对象失败:', error)
  }
}

const handleSubmitComment = async () => {
  if (!newComment.value.trim() || !task.value || !userStore.user) return
  
  submittingComment.value = true
  try {
    await taskStore.addComment(task.value.task_id, userStore.user.name || '匿名用户', newComment.value)
    newComment.value = ''
    ElMessage.success('评论添加成功')
  } catch (error) {
    console.error('添加评论失败:', error)
    ElMessage.error('添加评论失败')
  } finally {
    submittingComment.value = false
  }
}

const handleEdit = () => {
  if (!task.value) return
  
  editing.value = true
  editForm.value = {
    name: task.value.name,
    description: task.value.description,
    details: task.value.details || '',
    acceptance_criteria: task.value.acceptance_criteria || [],
    context_files: task.value.context_files || [],
    context_links: task.value.context_links || [],
    context_notes: task.value.context_notes || '',
    report: task.value.report || '',
  }
}

const handleSaveEdit = async () => {
  if (!task.value) return
  
  try {
    await taskStore.updateTask(task.value.task_id, editForm.value)
    editing.value = false
    ElMessage.success('任务更新成功')
  } catch (error) {
    console.error('更新任务失败:', error)
    ElMessage.error('更新任务失败')
  }
}

const handleCancelEdit = () => {
  editing.value = false
}

const formatDate = (dateString: string): string => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const getStatusInfo = (status: TaskStatus) => {
  return statusOptions.value.find(option => option.value === status) || statusOptions.value[0]
}

const getPriorityInfo = (priority: TaskPriority) => {
  return priorityOptions.value.find(option => option.value === priority) || priorityOptions.value[1]
}

// 监听任务ID变化
watch(() => props.taskId, (newTaskId) => {
  if (newTaskId && props.visible) {
    taskStore.fetchTaskDetail(newTaskId)
  }
})

// 监听抽屉可见性变化
watch(() => props.visible, (visible) => {
  if (visible && props.taskId) {
    taskStore.fetchTaskDetail(props.taskId)
  } else {
    editing.value = false
  }
})
</script>

<template>
  <el-drawer
    :model-value="visible"
    @update:model-value="handleClose"
    title="任务详情"
    size="50%"
    direction="rtl"
    class="task-detail-drawer"
  >
    <!-- 加载状态 -->
    <div v-if="loading" class="flex items-center justify-center h-full">
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <!-- 任务详情 -->
    <div v-else-if="task" class="h-full flex flex-col">
      <!-- 头部信息 -->
      <div class="border-b pb-4 mb-4">
        <!-- 编辑模式 -->
        <div v-if="editing" class="space-y-3">
          <el-input v-model="editForm.name" placeholder="任务名称" />
          <el-input v-model="editForm.description" type="textarea" placeholder="任务描述" :rows="2" />
          <el-input v-model="editForm.details" type="textarea" placeholder="详细描述" :rows="4" />
          <div class="flex gap-2">
            <el-button type="primary" @click="handleSaveEdit">保存</el-button>
            <el-button @click="handleCancelEdit">取消</el-button>
          </div>
        </div>

        <!-- 查看模式 -->
        <div v-else>
          <div class="flex items-start justify-between mb-3">
            <div class="flex-1">
              <h2 class="text-xl font-bold text-gray-900 mb-2">{{ task.name }}</h2>
              <p class="text-gray-600 mb-3">{{ task.description }}</p>
            </div>
            <el-button type="warning" circle @click="handleEdit">
              <el-icon><Edit /></el-icon>
            </el-button>
          </div>

          <div class="flex flex-wrap gap-2 mb-3">
            <!-- 状态 -->
            <el-dropdown @command="handleUpdateStatus">
              <el-tag :type="getStatusInfo(task.status).type" size="large" class="cursor-pointer">
                <el-icon class="mr-1">
                  <component :is="getStatusInfo(task.status).icon" />
                </el-icon>
                {{ getStatusInfo(task.status).label }}
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="option in statusOptions"
                    :key="option.value"
                    :command="option.value"
                    :disabled="option.value === task.status"
                  >
                    <el-icon class="mr-2">
                      <component :is="option.icon" />
                    </el-icon>
                    {{ option.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <!-- 优先级 -->
            <el-dropdown @command="handleUpdatePriority">
              <el-tag :type="getPriorityInfo(task.priority).type" size="large" class="cursor-pointer">
                {{ getPriorityInfo(task.priority).label }}
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="option in priorityOptions"
                    :key="option.value"
                    :command="option.value"
                    :disabled="option.value === task.priority"
                  >
                    {{ option.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <!-- 分配对象 -->
            <el-input
              v-model="task.assignee"
              placeholder="未分配"
              size="small"
              style="width: 120px"
              @blur="handleUpdateAssignee(task.assignee || '')"
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </div>

          <!-- 元信息 -->
          <div class="text-sm text-gray-500 space-y-1">
            <div>创建时间: {{ formatDate(task.created_at) }}</div>
            <div>更新时间: {{ formatDate(task.updated_at) }}</div>
            <div v-if="task.session_id">会话ID: {{ task.session_id }}</div>
            <div v-if="task.parent_id">父任务ID: {{ task.parent_id }}</div>
          </div>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="flex-1 overflow-y-auto space-y-6">
        <!-- 详细描述 -->
        <div v-if="task.details" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2 flex items-center gap-2">
            <el-icon><Document /></el-icon>
            详细描述
          </h3>
          <div class="text-gray-700 whitespace-pre-wrap">{{ task.details }}</div>
        </div>

        <!-- 验收标准 -->
        <div v-if="task.acceptance_criteria && task.acceptance_criteria.length > 0" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2">验收标准</h3>
          <ul class="space-y-2">
            <li v-for="(criterion, index) in task.acceptance_criteria" :key="index" class="flex items-start gap-2">
              <el-icon class="text-green-500 mt-0.5"><Check /></el-icon>
              <span class="text-gray-700">{{ criterion }}</span>
            </li>
          </ul>
        </div>

        <!-- 关联文件 -->
        <div v-if="task.context_files && task.context_files.length > 0" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2 flex items-center gap-2">
            <el-icon><Paperclip /></el-icon>
            关联文件
          </h3>
          <div class="space-y-1">
            <div v-for="(file, index) in task.context_files" :key="index" class="text-blue-600 hover:underline cursor-pointer">
              {{ file }}
            </div>
          </div>
        </div>

        <!-- 关联链接 -->
        <div v-if="task.context_links && task.context_links.length > 0" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2 flex items-center gap-2">
            <el-icon><Link /></el-icon>
            关联链接
          </h3>
          <div class="space-y-1">
            <a
              v-for="(link, index) in task.context_links"
              :key="index"
              :href="link"
              target="_blank"
              class="text-blue-600 hover:underline block truncate"
            >
              {{ link }}
            </a>
          </div>
        </div>

        <!-- 上下文笔记 -->
        <div v-if="task.context_notes" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2">上下文笔记</h3>
          <div class="text-gray-700 whitespace-pre-wrap">{{ task.context_notes }}</div>
        </div>

        <!-- 任务报告 -->
        <div v-if="task.report" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2">任务报告</h3>
          <div class="text-gray-700 whitespace-pre-wrap">{{ task.report }}</div>
        </div>

        <!-- 依赖关系 -->
        <div v-if="task.dependencies && task.dependencies.length > 0" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2">依赖任务</h3>
          <div class="space-y-1">
            <div v-for="(dependency, index) in task.dependencies" :key="index" class="text-gray-700">
              {{ dependency }}
            </div>
          </div>
        </div>

        <!-- 子任务 -->
        <div v-if="children.length > 0" class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-2">子任务 ({{ children.length }})</h3>
          <div class="space-y-2">
            <div
              v-for="child in children"
              :key="child.task_id"
              class="border rounded p-3 hover:bg-gray-50 cursor-pointer"
              @click="taskStore.openDetail(child.task_id)"
            >
              <div class="flex items-center justify-between">
                <div>
                  <div class="font-medium">{{ child.name }}</div>
                  <div class="text-sm text-gray-500">{{ child.description }}</div>
                </div>
                <div class="flex items-center gap-2">
                  <el-tag :type="getStatusInfo(child.status).type" size="small">
                    {{ getStatusInfo(child.status).label }}
                  </el-tag>
                  <el-tag :type="getPriorityInfo(child.priority).type" size="small">
                    {{ getPriorityInfo(child.priority).label }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 评论区域 -->
        <div class="border rounded-lg p-4">
          <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
            <el-icon><Message /></el-icon>
            评论 ({{ comments.length }})
          </h3>

          <!-- 评论列表 -->
          <div v-if="comments.length > 0" class="space-y-4 mb-4">
            <div v-for="comment in comments" :key="comment.comment_id" class="border-b pb-4 last:border-0">
              <div class="flex items-start justify-between mb-2">
                <div class="font-medium">{{ comment.author }}</div>
                <div class="text-sm text-gray-500">{{ formatDate(comment.created_at) }}</div>
              </div>
              <div class="text-gray-700 whitespace-pre-wrap">{{ comment.content }}</div>
            </div>
          </div>

          <!-- 添加评论 -->
          <div class="mt-4">
            <el-input
              v-model="newComment"
              type="textarea"
              placeholder="添加评论..."
              :rows="3"
              :disabled="submittingComment"
            />
            <div class="flex justify-end mt-2">
              <el-button
                type="primary"
                :loading="submittingComment"
                :disabled="!newComment.trim()"
                @click="handleSubmitComment"
              >
                <!-- <el-icon class="mr-1"><Send /></el-icon> -->
                发表评论
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 任务不存在 -->
    <div v-else class="flex flex-col items-center justify-center h-full text-gray-500">
      <el-icon size="48" class="mb-4">
        <Document />
      </el-icon>
      <p>任务不存在</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.task-detail-drawer :deep(.el-drawer__body) {
  padding: 20px;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .task-detail-drawer :deep(.el-drawer) {
    width: 100% !important;
  }
}
</style>
