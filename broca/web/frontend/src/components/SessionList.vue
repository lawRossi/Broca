<script setup lang="ts">
import { computed } from 'vue'
import SessionCard from './SessionCard.vue'
import type { Session } from '@/api/session'
import { Loading, FolderOpened } from '@element-plus/icons-vue'

interface Props {
  sessions: Session[]
  loading: boolean
  total: number
  currentPage: number
  pageSize: number
  selectedSessions: string[]
  deleteLoading: boolean
  showActions?: boolean
}

interface Emits {
  (e: 'page-change', page: number): void
  (e: 'size-change', size: number): void
  (e: 'select', sessionId: string): void
  (e: 'deselect', sessionId: string): void
  (e: 'delete', session: Session): void
  (e: 'batch-delete'): void
}

const props = withDefaults(defineProps<Props>(), {
  showActions: true
})

const emit = defineEmits<Emits>()

// 计算属性
const isAllSelected = computed(() => {
  return props.sessions.length > 0 && 
    props.selectedSessions.length === props.sessions.length
})

const isIndeterminate = computed(() => {
  return props.selectedSessions.length > 0 && 
    props.selectedSessions.length < props.sessions.length
})

// 全选/取消全选
const handleSelectAll = () => {
  if (isAllSelected.value) {
    // 取消全选当前页
    props.sessions.forEach(session => {
      if (props.selectedSessions.includes(session.session_id)) {
        emit('deselect', session.session_id)
      }
    })
  } else {
    // 全选当前页
    props.sessions.forEach(session => {
      if (!props.selectedSessions.includes(session.session_id)) {
        emit('select', session.session_id)
      }
    })
  }
}

// 分页变化
const handleCurrentChange = (page: number) => {
  emit('page-change', page)
}

const handleSizeChange = (size: number) => {
  emit('size-change', size)
}

// 单个会话操作
const handleSessionSelect = (sessionId: string) => {
  emit('select', sessionId)
}

const handleSessionDeselect = (sessionId: string) => {
  emit('deselect', sessionId)
}

const handleSessionDelete = (session: Session) => {
  emit('delete', session)
}

// 批量删除
const handleBatchDelete = () => {
  emit('batch-delete')
}
</script>

<template>
  <div class="session-list">
    <!-- 批量操作栏 - 固定在底部 -->
    <div
      v-if="selectedSessions.length > 0"
      class="fixed bottom-6 left-1/2 transform -translate-x-1/2 z-50 bg-white border border-blue-300 rounded-full shadow-lg px-6 py-3 flex items-center gap-4 transition-all duration-300"
      style="max-width: 90%;"
    >
      <div class="flex items-center gap-3">
        <el-checkbox
          :model-value="isAllSelected"
          :indeterminate="isIndeterminate"
          @change="handleSelectAll"
        >
          <span class="text-sm font-medium">已选择 {{ selectedSessions.length }} 项</span>
        </el-checkbox>
      </div>

      <div class="flex items-center gap-2">
        <el-button
          type="danger"
          size="small"
          :loading="deleteLoading"
          @click="handleBatchDelete"
        >
          批量删除
        </el-button>
      </div>
    </div>

    <!-- 加载状态 -->
    <div
      v-if="loading"
      class="flex items-center justify-center py-12"
    >
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <!-- 空状态 -->
    <div
      v-else-if="sessions.length === 0"
      class="flex flex-col items-center justify-center py-12 text-gray-500"
    >
      <el-icon size="48" class="mb-4">
        <FolderOpened />
      </el-icon>
      <p>暂无会话</p>
      <p class="text-sm mt-1">点击上方"创建会话"按钮开始</p>
    </div>

    <!-- 会话列表 -->
    <div
      v-else
      class="space-y-3"
    >
      <SessionCard
        v-for="session in sessions"
        :key="session.session_id"
        :session="session"
        :is-selected="selectedSessions.includes(session.session_id)"
        :show-actions="showActions"
        @select="handleSessionSelect"
        @deselect="handleSessionDeselect"
        @delete="handleSessionDelete"
      />
    </div>

    <!-- 分页器 -->
    <div
      v-if="!loading && total > 0"
      class="mt-4 bg-white rounded-lg shadow-sm border p-4"
    >
      <el-pagination
        :current-page="currentPage"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        size="small"
        @current-change="handleCurrentChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
.session-list {
  width: 100%;
}

/* 为底部固定栏添加底部间距，避免内容被遮挡 */
:deep(.main-content) {
  padding-bottom: 80px;
}

/* 优化移动端显示 */
@media (max-width: 640px) {
  .batch-actions {
    padding: 0.75rem 1rem;
    max-width: 95% !important;
  }
  
  .batch-actions .el-checkbox {
    margin-right: 0.5rem;
  }
  
  .batch-actions .el-button {
    padding: 0.375rem 0.75rem;
    font-size: 0.875rem;
  }
}
</style>
