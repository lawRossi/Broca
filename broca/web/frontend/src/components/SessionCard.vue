<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Delete, FolderOpened, ArrowRight, Calendar, Bell, Document, Edit, Check, Close, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatBeijingTime } from '@/utils/time'
import type { Session } from '@/api/session'
import { sessionApi } from '@/api/session'
import { useSessionStore } from '@/stores'

const router = useRouter()
const sessionStore = useSessionStore()

interface Props {
  session: Session
  isSelected: boolean
  jobCount?: number
  showActions?: boolean
}

interface Emits {
  (e: 'select', sessionId: string): void
  (e: 'deselect', sessionId: string): void
  (e: 'delete', session: Session): void
  (e: 'update', session: Session): void
}

const props = withDefaults(defineProps<Props>(), {
  showActions: true,
  jobCount: 0,
})

const emit = defineEmits<Emits>()

// 编辑相关状态
const isEditing = ref(false)
const editDescription = ref('')
const editing = ref(false)
const descriptionInputRef = ref<HTMLInputElement | null>(null)

// 状态类型映射（合并 session.status + runner_status）
const statusTypeMap: Record<string, string> = {
  active: 'success',
  completed: 'info',
  paused: 'warning',
  error: 'danger',
}

// 状态标签映射
const statusLabelMap: Record<string, string> = {
  active: '进行中',
  completed: '已完成',
  paused: '已暂停',
  error: '错误',
}

// Runner 状态映射
const runnerLabelMap: Record<string, string> = {
  alive: '运行中',
  starting: '启动中',
  error: '进程异常',
  dead: '已停止',
  none: '无进程',
}

const runnerTypeMap: Record<string, string> = {
  alive: 'success',
  starting: 'warning',
  error: 'danger',
  dead: 'info',
  none: 'info',
}

// 获取显示用的状态类型：优先使用 runner_status
const getDisplayStatusType = (session: Session) => {
  if (session.runner_status && session.runner_status !== 'none') {
    return runnerTypeMap[session.runner_status] || 'info'
  }
  return statusTypeMap[session.status] || 'info'
}

// 获取显示用的状态标签
const getDisplayStatusLabel = (session: Session) => {
  if (session.runner_status && session.runner_status !== 'none') {
    return runnerLabelMap[session.runner_status] || session.runner_status
  }
  return statusLabelMap[session.status] || session.status
}

// 截断ID显示
const truncateId = (id: string, length: number = 8) => {
  if (!id) return ''
  if (id.length <= length * 2 + 3) return id
  return `${id.slice(0, length)}...${id.slice(-length)}`
}

// 获取状态类型
const getStatusType = (status: string) => {
  return statusTypeMap[status] || 'info'
}

// 获取状态标签
const getStatusLabel = (status: string) => {
  return statusLabelMap[status] || status
}

// 复选框变化
const handleCheckboxChange = (checked: boolean) => {
  if (checked) {
    emit('select', props.session.session_id)
  } else {
    emit('deselect', props.session.session_id)
  }
}

// 卡片点击 - 跳转到聊天（不触发选中）
const handleCardClick = () => {
  if (isEditing.value) return // 编辑状态下不跳转
  router.push(`/chat/${props.session.session_id}`)
}

// 浏览文件点击
const handleBrowseFiles = (event: Event) => {
  event.stopPropagation()
  emit('deselect', props.session.session_id)

  if (!props.session.workspace) {
    ElMessage.warning('该会话没有工作空间')
    return
  }

  router.push({
    path: '/files',
    query: { path: props.session.workspace },
  })
}

// 删除点击
const handleDelete = (event: Event) => {
  event.stopPropagation()
  emit('deselect', props.session.session_id)
  emit('delete', props.session)
}

// 查看定时任务
const handleViewJobs = (event: Event) => {
  event.stopPropagation()
  router.push({
    path: '/jobs',
    query: { session_id: props.session.session_id },
  })
}

// 管理任务（跳转到任务管理页面）
const handleManageTasks = (event: Event) => {
  event.stopPropagation()
  router.push({
    path: '/tasks',
    query: { session_id: props.session.session_id },
  })
}

// 开始编辑描述
const startEdit = (event: Event) => {
  event.stopPropagation()
  isEditing.value = true
  editDescription.value = props.session.description || ''

  // 聚焦到输入框
  nextTick(() => {
    descriptionInputRef.value?.focus()
    descriptionInputRef.value?.select()
  })
}

// 保存编辑
const saveEdit = async () => {
  if (!editDescription.value.trim()) {
    ElMessage.warning('描述不能为空')
    return
  }

  if (editDescription.value === props.session.description) {
    isEditing.value = false
    return
  }

  editing.value = true
  try {
    await sessionStore.updateSession(props.session.session_id, {
      description: editDescription.value.trim(),
    })

    // 更新本地会话对象
    const updatedSession = { ...props.session, description: editDescription.value.trim() }
    emit('update', updatedSession)

    isEditing.value = false
  } catch (error) {
    console.error('更新会话描述失败:', error)
  } finally {
    editing.value = false
  }
}

// 取消编辑
const cancelEdit = () => {
  isEditing.value = false
  editDescription.value = ''
}

// 处理键盘事件
const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter') {
    event.preventDefault()
    saveEdit()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    cancelEdit()
  }
}

// 重启 Runner 进程
const handleRestartRunner = async () => {
  try {
    await ElMessageBox.confirm('该会话的后台进程异常，是否重启？', '重启确认', {
      confirmButtonText: '重启',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await sessionApi.restartRunner(props.session.session_id)
    ElMessage.success('进程已重启')
    // 刷新列表
    sessionStore.refresh()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('重启失败: ' + (error.message || '未知错误'))
    }
  }
}
</script>

<template>
  <div
    class="session-card bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md hover:border-blue-300 transition-all duration-200 cursor-pointer relative"
    :class="{ 'ring-2 ring-blue-500': isSelected }"
    @click="handleCardClick"
  >
    <!-- 顶部：复选框、ID、状态 -->
    <div class="flex items-start justify-between mb-3">
      <div class="flex items-start gap-3 flex-1 min-w-0">
        <!-- 选择复选框 -->
        <el-checkbox :model-value="isSelected" @change="handleCheckboxChange" @click.stop />

        <!-- ID 和描述 -->
        <div class="flex-1 min-w-0">
          <div class="font-mono text-xs text-gray-500 mb-1">
            {{ truncateId(session.session_id, 10) }}
          </div>

          <!-- 描述显示/编辑区域 -->
          <div class="flex items-center gap-2">
            <!-- 显示模式 -->
            <div v-if="!isEditing" class="flex items-center gap-2 flex-1">
              <div class="text-gray-900 font-medium truncate cursor-text" @dblclick="startEdit">
                {{ session.description || '无描述' }}
              </div>
              <!-- 编辑小图标 -->
              <el-icon
                class="text-gray-400 hover:text-blue-500 cursor-pointer transition-colors"
                size="14"
                @click.stop="startEdit"
                title="编辑描述"
              >
                <Edit />
              </el-icon>
            </div>

            <!-- 编辑模式 -->
            <div v-else class="flex items-center gap-2 flex-1 flex-col">
              <el-input
                ref="descriptionInputRef"
                v-model="editDescription"
                size="small"
                placeholder="请输入会话描述"
                maxlength="200"
                show-word-limit
                @keydown="handleKeydown"
                @blur="saveEdit"
                class="flex-1 w-full"
              />
              <div class="flex items-center gap-1">
                <el-button
                  type="success"
                  size="small"
                  :loading="editing"
                  :icon="Check"
                  @click.stop="saveEdit"
                  title="保存"
                />
                <el-button type="info" size="small" :icon="Close" @click.stop="cancelEdit" title="取消" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 状态标签（合并 session.status + runner_status） -->
      <div class="ml-3 flex-shrink-0 flex items-center gap-1">
        <el-tag
          :type="getDisplayStatusType(session)"
          size="small"
          effect="plain"
        >
          {{ getDisplayStatusLabel(session) }}
        </el-tag>
        <!-- 心跳异常额外标记 -->
        <el-tooltip
          v-if="session.runner_status === 'error'"
          content="后台进程异常，点击重启"
          placement="top"
        >
          <el-icon class="text-red-500 cursor-pointer" size="14" @click.stop="handleRestartRunner">
            <WarningFilled />
          </el-icon>
        </el-tooltip>
      </div>
    </div>

    <!-- 底部：创建时间、操作按钮 -->
    <div class="flex items-center justify-between text-sm text-gray-500">
      <div class="flex items-center gap-1">
        <el-icon class="text-xs">
          <Calendar />
        </el-icon>
        <span>{{ formatBeijingTime(session.created_at).split(' ')[0] }}</span>
      </div>

      <!-- 操作按钮组 -->
      <div v-if="showActions" class="flex items-center gap-2">
        <!-- 文件浏览按钮 -->
        <el-button
          v-if="session.workspace"
          type="primary"
          size="small"
          plain
          :disabled="isEditing"
          :title="`浏览工作空间: ${session.workspace}`"
          @click.stop="handleBrowseFiles"
        >
          <el-icon class="mr-1">
            <FolderOpened />
          </el-icon>
          文件
        </el-button>

        <!-- 定时任务按钮 -->
        <el-button
          type="info"
          size="small"
          plain
          :disabled="isEditing"
          :title="`查看定时任务${jobCount ? ` (${jobCount})` : ''}`"
          @click.stop="handleViewJobs"
        >
          <el-icon class="mr-1">
            <Bell />
          </el-icon>
          定时任务
          <el-badge v-if="jobCount && jobCount > 0" :value="jobCount" class="ml-1" type="info" is-dot />
        </el-button>

        <!-- 任务管理按钮 -->
        <el-button
          type="success"
          size="small"
          plain
          :disabled="isEditing"
          title="管理任务"
          @click.stop="handleManageTasks"
        >
          <el-icon class="mr-1">
            <Document />
          </el-icon>
          管理任务
        </el-button>

        <!-- 删除按钮 -->
        <el-button type="danger" size="small" plain :disabled="isEditing" @click.stop="handleDelete">
          <el-icon class="mr-1">
            <Delete />
          </el-icon>
          删除
        </el-button>
      </div>

      <!-- 桌面端显示箭头 -->
      <el-icon v-else class="text-gray-400">
        <ArrowRight />
      </el-icon>
    </div>
  </div>
</template>

<style scoped>
.smooth-transition {
  transition: all 0.2s ease;
}

.smooth-transition:active {
  transform: scale(0.98);
}

/* 选中状态 */
:deep(.el-checkbox) {
  --el-checkbox-checked-text-color: #3b82f6;
  --el-checkbox-checked-bg-color: #3b82f6;
  --el-checkbox-checked-border-color: #3b82f6;
}

/* 状态标签 */
:deep(.el-tag) {
  border-radius: 9999px;
  font-weight: 500;
}

/* 按钮样式 */
:deep(.el-button--small) {
  border-radius: 6px;
  font-weight: 500;
}

/* 移动端优化 */
@media (max-width: 640px) {
  .session-card {
    padding: 0.75rem 1rem;
  }

  .session-card .flex.items-start.gap-3 {
    gap: 0.75rem;
  }

  /* 描述区域优化 - 确保靠左对齐 */
  .session-card .flex-1.min-w-0 {
    min-width: 0;
    width: 100%;
  }

  /* 描述显示区域 */
  .session-card .flex.items-center.gap-2 {
    align-items: flex-start;
    width: 100%;
  }

  /* 显示模式 - 确保描述和图标在同一行且靠左 */
  .session-card .flex.items-center.gap-2.flex-1:not(.flex-col) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
  }

  .session-card .text-gray-900 {
    max-width: calc(100% - 24px); /* 为编辑图标留出空间 */
    font-size: 0.875rem;
    text-align: left;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* 编辑图标 */
  .session-card .el-icon.text-gray-400 {
    flex-shrink: 0;
    margin-left: 4px;
  }

  /* 编辑模式 - 垂直布局 */
  .session-card .flex.items-center.gap-2.flex-1.flex-col {
    flex-direction: column;
    align-items: stretch;
    gap: 0.5rem;
  }

  .session-card .el-input {
    width: 100%;
  }

  .session-card .flex.items-center.gap-1 {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }

  /* ID 字体更小 */
  .session-card .font-mono.text-xs {
    font-size: 0.7rem;
    text-align: left;
  }

  /* 操作按钮垂直排列或缩小 */
  .session-card .flex.items-center.gap-2 {
    gap: 0.25rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .session-card .el-button--small {
    padding: 4px 8px;
    font-size: 0.75rem;
    min-height: auto;
  }

  .session-card .el-button .el-icon {
    font-size: 12px;
  }

  /* 徽章缩小 */
  .session-card .el-badge {
    font-size: 0.7rem;
  }

  /* 状态标签缩小 */
  .session-card .el-tag--small {
    height: 18px;
    padding: 0 6px;
    font-size: 10px;
    line-height: 16px;
  }

  /* 时间显示 */
  .session-card .text-sm.text-gray-500 {
    font-size: 0.75rem;
  }
}
</style>
