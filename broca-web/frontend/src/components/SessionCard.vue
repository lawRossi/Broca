<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  Delete,
  FolderOpened,
  ArrowRight,
  Calendar,
  Bell,
  Document,
  Edit,
  Check,
  Close,
  WarningFilled,
  VideoPlay,
  VideoPause,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatTime } from '@/utils/time'
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

// 会话分类判断
const isNormalSession = computed(() => {
  return !props.session.category || props.session.category === 'normal'
})

const isAgentOrchestrationSession = computed(() => {
  return props.session.category === 'agent-orchestration'
})

// 状态类型映射（仅使用 runner_status）
const statusTypeMap: Record<string, string> = {
  alive: 'success',
  starting: 'warning',
  error: 'danger',
  dead: 'info',
  none: 'info',
}

// 状态标签映射
const statusLabelMap: Record<string, string> = {
  alive: '运行中',
  starting: '启动中',
  error: '进程异常',
  dead: '已停止',
  none: '未运行',
}

// 获取显示用的状态类型
const getDisplayStatusType = (session: Session) => {
  const status = session.runner_status || 'none'
  return statusTypeMap[status] || 'info'
}

// 获取显示用的状态标签
const getDisplayStatusLabel = (session: Session) => {
  const status = session.runner_status || 'none'
  return statusLabelMap[status] || status
}

// 截断ID显示
const truncateId = (id: string, length: number = 8) => {
  if (!id) return ''
  if (id.length <= length * 2 + 3) return id
  return `${id.slice(0, length)}...${id.slice(-length)}`
}

// 复选框变化
const handleCheckboxChange = (checked: boolean) => {
  if (checked) {
    emit('select', props.session.session_id)
  } else {
    emit('deselect', props.session.session_id)
  }
}

// 卡片点击 - 根据类型跳转
const handleCardClick = () => {
  if (isEditing.value) return // 编辑状态下不跳转
  if (isAgentOrchestrationSession.value) {
    // Agent 编排会话 -> 跳转到编排管理
    router.push(`/crews?session_id=${props.session.session_id}`)
  } else {
    // 普通会话 -> 跳转到聊天
    router.push(`/chat/${props.session.session_id}`)
  }
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
const handleDelete = async (event: Event) => {
  event.stopPropagation()
  if (sessionStore.isDeleting(props.session.session_id)) return

  // 先显示确认对话框
  try {
    await ElMessageBox.confirm('确定要删除这个会话吗？此操作不可恢复。', '确认删除', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }

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

// Runner 进程启停
const togglingRunner = ref(false)

const handleToggleRunner = async () => {
  if (togglingRunner.value) return
  togglingRunner.value = true

  try {
    const status = props.session.runner_status || 'none'
    if (status === 'alive') {
      // 运行中 → 停止
      await ElMessageBox.confirm('确定要停止该会话的后台进程吗？停止后需要手动启动才能继续使用。', '停止确认', {
        confirmButtonText: '停止',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await sessionApi.stopRunner(props.session.session_id)
      ElMessage.success('进程已停止')
    } else {
      // 已停止/异常/未运行 → 启动（重启）
      await sessionApi.restartRunner(props.session.session_id)
      ElMessage.success('进程已启动')
    }
    // 刷新列表
    sessionStore.refresh()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('操作失败: ' + (error.message || '未知错误'))
    }
  } finally {
    togglingRunner.value = false
  }
}
</script>

<template>
  <div
    class="session-card bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md hover:border-blue-300 transition-all duration-200 cursor-pointer relative"
    :class="{ 'ring-2 ring-blue-500': isSelected }"
    @click="handleCardClick"
  >
    <!-- 第一行：描述 + 状态标签 -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-3 flex-1 min-w-0">
        <!-- 选择复选框 -->
        <el-checkbox :model-value="isSelected" @change="handleCheckboxChange" @click.stop />

        <!-- 描述显示/编辑区域 -->
        <div v-if="!isEditing" class="flex items-center gap-2 flex-1 min-w-0">
          <div class="text-gray-900 font-medium truncate cursor-text" @dblclick="startEdit">
            {{ session.description || '无描述' }}
          </div>
          <el-icon
            class="text-gray-400 hover:text-blue-500 cursor-pointer transition-colors flex-shrink-0"
            size="14"
            title="编辑描述"
            @click.stop="startEdit"
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
            class="flex-1 w-full"
            @keydown="handleKeydown"
            @blur="saveEdit"
          />
          <div class="flex items-center gap-1">
            <el-button
              type="success"
              size="small"
              :loading="editing"
              :icon="Check"
              title="保存"
              @click.stop="saveEdit"
            />
            <el-button type="info" size="small" :icon="Close" title="取消" @click.stop="cancelEdit" />
          </div>
        </div>
      </div>

      <!-- 状态标签 -->
      <div class="flex-shrink-0 flex items-center gap-1 ml-2">
        <el-tag v-if="session.category === 'agent-orchestration'" type="warning" size="small" effect="light">
          📝 编排
        </el-tag>
        <el-tag :type="getDisplayStatusType(session)" size="small" effect="plain">
          {{ getDisplayStatusLabel(session) }}
        </el-tag>
        <el-tooltip v-if="session.runner_status === 'error'" content="后台进程异常，点击重启" placement="top">
          <el-icon class="text-red-500 cursor-pointer" size="14" @click.stop="handleToggleRunner">
            <WarningFilled />
          </el-icon>
        </el-tooltip>
      </div>
    </div>

    <!-- 第二行：ID、Workspace、创建时间、操作按钮 -->
    <!-- 桌面端：[ID workspace]  🕐时间                [文件] [启动] [删除] -->
    <!-- 移动端：[ID workspace]                [文件] [启动] [删除] -->
    <!--        🕐时间                                                    -->
    <div class="flex items-center text-sm text-gray-500 session-meta-row">
      <div class="flex items-center gap-3 min-w-0 session-meta-left">
        <span class="font-mono text-xs truncate max-w-[120px]" :title="session.session_id">
          ID: {{ truncateId(session.session_id, 12) }}
        </span>
        <span v-if="session.workspace" class="truncate max-w-[160px]" :title="session.workspace">
          📁 {{ session.workspace.length > 20 ? session.workspace.slice(0, 20) + '...' : session.workspace }}
        </span>
      </div>

      <span class="session-time">
        🕐
        {{
          formatTime(
            session.created_at
              ? session.created_at.includes('T') &&
                !session.created_at.endsWith('Z') &&
                !session.created_at.includes('+')
                ? session.created_at + 'Z'
                : session.created_at
              : null
          ).slice(0, 16)
        }}
      </span>

      <!-- 操作按钮组 -->
      <div v-if="showActions" class="flex items-center gap-2 flex-shrink-0 session-actions">
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
        <el-button
          :type="session.runner_status === 'alive' ? 'warning' : 'primary'"
          size="small"
          plain
          :disabled="isEditing || session.runner_status === 'starting'"
          :loading="togglingRunner"
          :title="session.runner_status === 'alive' ? '停止进程' : '启动进程'"
          @click.stop="handleToggleRunner"
        >
          <el-icon class="mr-1">
            <VideoPlay v-if="session.runner_status !== 'alive'" />
            <VideoPause v-else />
          </el-icon>
          {{ session.runner_status === 'alive' ? '停止' : session.runner_status === 'starting' ? '启动中' : '启动' }}
        </el-button>
        <el-button
          type="danger"
          size="small"
          plain
          :disabled="isEditing || sessionStore.isDeleting(session.session_id)"
          :loading="sessionStore.isDeleting(session.session_id)"
          @click.stop="handleDelete"
        >
          <el-icon v-if="!sessionStore.isDeleting(session.session_id)" class="mr-1">
            <Delete />
          </el-icon>
          {{ sessionStore.isDeleting(session.session_id) ? '删除中...' : '删除' }}
        </el-button>
      </div>

      <!-- 桌面端显示箭头 -->
      <el-icon v-else class="flex-shrink-0 session-arrow">
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

/* 第二行：flex 布局控制 */
.session-meta-row {
  display: flex;
  align-items: center;
}

.session-meta-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  order: 1;
}

.session-time {
  order: 2;
  margin-left: 12px;
  flex-shrink: 0;
}

.session-actions,
.session-arrow {
  order: 3;
  margin-left: auto;
}

/* 移动端优化 */
@media (max-width: 640px) {
  .session-meta-row {
    flex-wrap: wrap;
  }
  .session-time {
    order: 3;
    width: 100%;
    margin-left: 0;
    margin-top: 4px;
  }
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
