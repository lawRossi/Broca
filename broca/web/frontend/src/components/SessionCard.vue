<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Delete, FolderOpened, ArrowRight, Calendar } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatBeijingTime } from '@/utils/time'
import type { Session } from '@/api/session'

const router = useRouter()

interface Props {
  session: Session
  isSelected: boolean
  showActions?: boolean
}

interface Emits {
  (e: 'select', sessionId: string): void
  (e: 'deselect', sessionId: string): void
  (e: 'delete', session: Session): void
}

const props = withDefaults(defineProps<Props>(), {
  showActions: true
})

const emit = defineEmits<Emits>()

// 状态类型映射
const statusTypeMap: Record<string, string> = {
  active: 'success',
  completed: 'info',
  paused: 'warning',
  error: 'danger'
}

// 状态标签映射
const statusLabelMap: Record<string, string> = {
  active: '进行中',
  completed: '已完成',
  paused: '已暂停',
  error: '错误'
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
    query: { path: props.session.workspace }
  })
}

// 删除点击
const handleDelete = async (event: Event) => {
  event.stopPropagation()
  emit('deselect', props.session.session_id)
  
  try {
    await ElMessageBox.confirm(
      `确定要删除会话 "${props.session.description || '无描述'}" 吗？`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    emit('delete', props.session)
  } catch {
    // 用户取消
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
        <el-checkbox
          :model-value="isSelected"
          @change="handleCheckboxChange"
          @click.stop
        />
        
        <!-- ID 和描述 -->
        <div class="flex-1 min-w-0">
          <div class="font-mono text-xs text-gray-500 mb-1">
            {{ truncateId(session.session_id, 10) }}
          </div>
          <div class="text-gray-900 font-medium truncate">
            {{ session.description || '无描述' }}
          </div>
        </div>
      </div>

      <!-- 状态标签 -->
      <div class="ml-3 flex-shrink-0">
        <el-tag :type="getStatusType(session.status)" size="small" effect="plain">
          {{ getStatusLabel(session.status) }}
        </el-tag>
      </div>
    </div>

    <!-- 底部：创建时间、操作按钮 -->
    <div class="flex items-center justify-between text-sm text-gray-500">
      <div class="flex items-center gap-1">
        <el-icon class="text-xs"><Calendar /></el-icon>
        <span>{{ formatBeijingTime(session.created_at).split(' ')[0] }}</span>
      </div>

      <!-- 操作按钮组 -->
      <div v-if="showActions" class="flex items-center gap-2">
        <el-button
          v-if="session.workspace"
          type="primary"
          size="small"
          plain
          @click.stop="handleBrowseFiles"
          :title="`浏览工作空间: ${session.workspace}`"
        >
          <el-icon class="mr-1"><FolderOpened /></el-icon>
          文件
        </el-button>
        <el-button
          type="danger"
          size="small"
          plain
          @click.stop="handleDelete"
        >
          <el-icon class="mr-1"><Delete /></el-icon>
          删除
        </el-button>
      </div>

      <!-- 桌面端显示箭头 -->
      <el-icon v-else class="text-gray-400"><ArrowRight /></el-icon>
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
</style>
