<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { taskApi } from '../utils/api'
import type { Task, TaskDetail, TaskComment, ChildTask } from '../types'

const props = defineProps<{
  sessionId?: string
}>()

// ==================== State ====================
const tasks = ref<Task[]>([])
const loading = ref(false)
const total = ref(0)
const skip = ref(0)
const limit = ref(50)
const errorMsg = ref('')

const searchKeyword = ref('')
const statusFilter = ref('')
const priorityFilter = ref('')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '待处理', value: 'pending' },
  { label: '进行中', value: 'in_progress' },
  { label: '已阻塞', value: 'blocked' },
  { label: '已完成', value: 'completed' },
]

const priorityOptions = [
  { label: '全部优先级', value: '' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]

// Detail drawer
const showDetail = ref(false)
const detailLoading = ref(false)
const taskDetail = ref<TaskDetail | null>(null)
const selectedTaskId = ref<string>('')
const newComment = ref('')
const submittingComment = ref(false)

// Create dialog
const showCreateDialog = ref(false)
const newTaskName = ref('')
const newTaskDesc = ref('')

// Edit mode for detail
const editing = ref(false)
const editForm = ref({
  name: '',
  description: '',
  details: '',
  report: '',
})

// Confirm dialog
const confirmDialog = ref({
  visible: false,
  message: '',
  onConfirm: null as (() => void) | null,
})

function showConfirm(message: string, onConfirm: () => void) {
  confirmDialog.value = { visible: true, message, onConfirm }
}

// ==================== Status helpers ====================
const statusLabels: Record<string, string> = {
  pending: '待处理',
  in_progress: '进行中',
  blocked: '已阻塞',
  completed: '已完成',
}

const priorityLabels: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

function getStatusClass(status: string): string {
  switch (status) {
    case 'pending': return 'status-pending'
    case 'in_progress': return 'status-progress'
    case 'blocked': return 'status-blocked'
    case 'completed': return 'status-completed'
    default: return ''
  }
}

function getPriorityClass(priority: string): string {
  switch (priority) {
    case 'low': return 'priority-low'
    case 'medium': return 'priority-medium'
    case 'high': return 'priority-high'
    default: return 'priority-medium'
  }
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins}分钟前`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}小时前`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days}天前`
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return dateStr
  }
}

// ==================== Actions ====================
async function fetchTasks() {
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await taskApi.getTasks({
      skip: skip.value,
      limit: limit.value,
      status: statusFilter.value || undefined,
      priority: priorityFilter.value || undefined,
      keyword: searchKeyword.value || undefined,
      session_id: props.sessionId || undefined,
    })
    console.log('[TaskPage] API response:', response)
    tasks.value = response.tasks || response || []
    total.value = response.total || (Array.isArray(response) ? response.length : tasks.value.length)
    if (Array.isArray(response)) {
      total.value = response.length
    }
  } catch (e: any) {
    console.error('[TaskPage] Failed to fetch tasks:', e)
    errorMsg.value = `加载失败: ${e.message || e}`
  } finally {
    loading.value = false
  }
}

async function openDetail(taskId: string) {
  selectedTaskId.value = taskId
  detailLoading.value = true
  showDetail.value = true
  try {
    const detail = await taskApi.getTaskDetail(taskId)
    taskDetail.value = detail
    editForm.value = {
      name: detail.task.name,
      description: detail.task.description,
      details: detail.task.details || '',
      report: detail.task.report || '',
    }
  } catch (e: any) {
    console.error('Failed to fetch task detail:', e)
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  showDetail.value = false
  taskDetail.value = null
  editing.value = false
  newComment.value = ''
}

async function handleUpdateStatus(taskId: string, status: string) {
  try {
    await taskApi.updateTask(taskId, { status })
    await fetchTasks()
    if (taskDetail.value?.task.task_id === taskId) {
      await openDetail(taskId)
    }
  } catch (e: any) {
    console.error('Failed to update status:', e)
  }
}

async function handleUpdatePriority(taskId: string, priority: string) {
  try {
    await taskApi.updateTask(taskId, { priority })
    await fetchTasks()
    if (taskDetail.value?.task.task_id === taskId) {
      await openDetail(taskId)
    }
  } catch (e: any) {
    console.error('Failed to update priority:', e)
  }
}

async function handleDeleteTask(taskId: string) {
  showConfirm('确定要删除这个任务吗？此操作不可恢复。', async () => {
    try {
      await taskApi.deleteTask(taskId)
      if (showDetail.value && selectedTaskId.value === taskId) {
        closeDetail()
      }
      await fetchTasks()
    } catch (e: any) {
      console.error('Failed to delete task:', e)
    }
  })
}

async function handleSaveEdit() {
  if (!taskDetail.value) return
  try {
    await taskApi.updateTask(selectedTaskId.value, editForm.value)
    editing.value = false
    await openDetail(selectedTaskId.value)
    await fetchTasks()
  } catch (e: any) {
    console.error('Failed to update task:', e)
  }
}

async function handleAddComment() {
  if (!newComment.value.trim() || !taskDetail.value) return
  submittingComment.value = true
  try {
    await taskApi.addComment(selectedTaskId.value, {
      author: 'user',
      content: newComment.value,
    })
    newComment.value = ''
    await openDetail(selectedTaskId.value)
  } catch (e: any) {
    console.error('Failed to add comment:', e)
  } finally {
    submittingComment.value = false
  }
}

async function handleCreateTask() {
  if (!newTaskName.value.trim()) return
  try {
    await taskApi.createTask({
      name: newTaskName.value.trim(),
      description: newTaskDesc.value.trim(),
    })
    newTaskName.value = ''
    newTaskDesc.value = ''
    showCreateDialog.value = false
    await fetchTasks()
  } catch (e: any) {
    console.error('Failed to create task:', e)
  }
}

function onSearch() {
  skip.value = 0
  fetchTasks()
}

onMounted(() => {
  fetchTasks()
})

// 当 sessionId 变化时重新加载
watch(() => props.sessionId, () => {
  fetchTasks()
})
</script>

<template>
  <div class="task-page">
    <!-- Header -->
    <div class="page-header">
      <div class="header-left">
        <h2>📋 任务管理</h2>
        <span class="header-count">共 {{ total }} 个任务</span>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" @click="showCreateDialog = true">+ 新建任务</button>
        <button class="btn btn-secondary" :disabled="loading" @click="fetchTasks">🔄 刷新</button>
      </div>
    </div>

    <!-- Filters -->
    <div class="filters">
      <input
        v-model="searchKeyword"
        class="filter-input"
        placeholder="搜索任务名称、ID或描述"
        @keyup.enter="onSearch"
      />
      <select v-model="statusFilter" class="filter-select" @change="onSearch">
        <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <select v-model="priorityFilter" class="filter-select" @change="onSearch">
        <option v-for="opt in priorityOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <span v-if="props.sessionId" class="filter-tag">会话: {{ props.sessionId.slice(0, 8) }}...</span>
    </div>

    <!-- Task List -->
    <div class="task-list">
      <div v-if="loading" class="loading-state">加载中...</div>
      <div v-else-if="errorMsg" class="error-state">{{ errorMsg }}</div>
      <div v-else-if="tasks.length === 0" class="empty-state">暂无任务</div>
      <div
        v-for="task in tasks"
        v-else
        :key="task.task_id"
        class="task-item"
        @click="openDetail(task.task_id)"
      >
        <div class="task-main">
          <div class="task-status-dot" :class="getStatusClass(task.status)"></div>
          <div class="task-content">
            <div class="task-name">{{ task.name }}</div>
            <div class="task-desc">{{ task.description || '无描述' }}</div>
          </div>
        </div>
        <div class="task-meta">
          <span class="tag" :class="getStatusClass(task.status)">{{ statusLabels[task.status] || task.status }}</span>
          <span class="tag" :class="getPriorityClass(task.priority)">{{ priorityLabels[task.priority] || task.priority }}</span>
          <span class="task-time">{{ formatDate(task.updated_at) }}</span>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <div v-if="showCreateDialog" class="dialog-overlay" @click.self="showCreateDialog = false">
      <div class="dialog">
        <h3>新建任务</h3>
        <input v-model="newTaskName" class="dialog-input" placeholder="任务名称" />
        <textarea v-model="newTaskDesc" class="dialog-textarea" placeholder="任务描述" rows="3"></textarea>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="showCreateDialog = false">取消</button>
          <button class="btn btn-primary" :disabled="!newTaskName.trim()" @click="handleCreateTask">创建</button>
        </div>
      </div>
    </div>

    <!-- Detail Drawer -->
    <div v-if="showDetail" class="drawer-overlay" @click.self="closeDetail">
      <div class="drawer">
        <div class="drawer-header">
          <h3>任务详情</h3>
          <button class="btn-close" @click="closeDetail">✕</button>
        </div>
        <div class="drawer-body">
          <div v-if="detailLoading" class="loading-state">加载中...</div>
          <div v-else-if="!taskDetail" class="empty-state">任务不存在</div>
          <template v-else>
            <!-- Basic info -->
            <div class="detail-section">
              <div v-if="editing" class="edit-form">
                <input v-model="editForm.name" class="dialog-input" placeholder="任务名称" />
                <textarea v-model="editForm.description" class="dialog-textarea" placeholder="任务描述" rows="2"></textarea>
                <textarea v-model="editForm.details" class="dialog-textarea" placeholder="详细描述" rows="4"></textarea>
                <textarea v-model="editForm.report" class="dialog-textarea" placeholder="任务报告" rows="3"></textarea>
                <div class="edit-actions">
                  <button class="btn btn-primary" @click="handleSaveEdit">保存</button>
                  <button class="btn btn-secondary" @click="editing = false">取消</button>
                </div>
              </div>
              <div v-else>
                <div class="detail-title-row">
                  <h4>{{ taskDetail.task.name }}</h4>
                  <button class="btn btn-sm" @click="editing = true">✏️ 编辑</button>
                </div>
                <p class="detail-desc">{{ taskDetail.task.description }}</p>
                <div class="detail-tags">
                  <span class="tag" :class="getStatusClass(taskDetail.task.status)">
                    {{ statusLabels[taskDetail.task.status] }}
                  </span>
                  <span class="tag" :class="getPriorityClass(taskDetail.task.priority)">
                    {{ priorityLabels[taskDetail.task.priority] }}
                  </span>
                  <span v-if="taskDetail.task.assignee" class="tag tag-assignee">
                    👤 {{ taskDetail.task.assignee }}
                  </span>
                </div>
                <div class="detail-info">
                  <span>创建: {{ formatDate(taskDetail.task.created_at) }}</span>
                  <span>更新: {{ formatDate(taskDetail.task.updated_at) }}</span>
                </div>
              </div>
            </div>

            <!-- Quick actions -->
            <div class="detail-section">
              <h5>操作</h5>
              <div class="action-buttons">
                <select
                  class="filter-select action-select"
                  :value="taskDetail.task.status"
                  @change="(e: any) => handleUpdateStatus(taskDetail!.task.task_id, e.target.value)"
                >
                  <option value="pending">📋 待处理</option>
                  <option value="in_progress">🔄 进行中</option>
                  <option value="blocked">⚠️ 已阻塞</option>
                  <option value="completed">✅ 已完成</option>
                </select>
                <select
                  class="filter-select action-select"
                  :value="taskDetail.task.priority"
                  @change="(e: any) => handleUpdatePriority(taskDetail!.task.task_id, e.target.value)"
                >
                  <option value="low">🟢 低优先级</option>
                  <option value="medium">🟡 中优先级</option>
                  <option value="high">🔴 高优先级</option>
                </select>
                <button class="btn btn-danger btn-sm" @click="handleDeleteTask(taskDetail.task.task_id)">🗑️ 删除</button>
              </div>
            </div>

            <!-- Details -->
            <div v-if="taskDetail.task.details" class="detail-section">
              <h5>详细描述</h5>
              <pre class="detail-pre">{{ taskDetail.task.details }}</pre>
            </div>

            <!-- Report -->
            <div v-if="taskDetail.task.report" class="detail-section">
              <h5>任务报告</h5>
              <pre class="detail-pre">{{ taskDetail.task.report }}</pre>
            </div>

            <!-- Children -->
            <div v-if="taskDetail.children && taskDetail.children.length > 0" class="detail-section">
              <h5>子任务 ({{ taskDetail.children.length }})</h5>
              <div v-for="child in taskDetail.children" :key="child.task_id" class="child-item">
                <span class="tag" :class="getStatusClass(child.status)">{{ statusLabels[child.status] }}</span>
                <span>{{ child.name }}</span>
              </div>
            </div>

            <!-- Comments -->
            <div class="detail-section">
              <h5>评论 ({{ taskDetail.comments?.length || 0 }})</h5>
              <div v-if="!taskDetail.comments || taskDetail.comments.length === 0" class="empty-state-sm">暂无评论</div>
              <div v-for="comment in taskDetail.comments" :key="comment.comment_id" class="comment-item">
                <div class="comment-header">
                  <strong>{{ comment.author }}</strong>
                  <span class="comment-time">{{ formatDate(comment.created_at) }}</span>
                </div>
                <p class="comment-content">{{ comment.content }}</p>
              </div>
              <div class="comment-input-row">
                <input
                  v-model="newComment"
                  class="filter-input"
                  placeholder="添加评论..."
                  :disabled="submittingComment"
                  @keyup.enter="handleAddComment"
                />
                <button
                  class="btn btn-primary btn-sm"
                  :disabled="!newComment.trim() || submittingComment"
                  @click="handleAddComment"
                >
                  发表
                </button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Confirm Dialog -->
  </div>
  <div v-if="confirmDialog.visible" class="dialog-overlay" @click.self="confirmDialog.visible = false">
    <div class="dialog dialog-confirm">
      <p>{{ confirmDialog.message }}</p>
      <div class="dialog-actions">
        <button class="btn btn-secondary" @click="confirmDialog.visible = false">取消</button>
        <button class="btn btn-danger" @click="() => { const cb = confirmDialog.onConfirm; confirmDialog.visible = false; cb?.(); }">确定删除</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px;
  gap: 10px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h2 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-count {
  font-size: 12px;
  color: var(--text-secondary);
}

.header-actions {
  display: flex;
  gap: 6px;
}

/* ==================== Buttons ==================== */
.btn {
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.btn:hover {
  background: var(--bg-tertiary);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
  border-color: var(--button-bg);
}

.btn-primary:hover {
  background: var(--button-hover-bg);
}

.btn-secondary {
  background: var(--bg-secondary);
}

.btn-danger {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error-fg, #ef4444);
  border-color: rgba(239, 68, 68, 0.3);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

.btn-sm {
  padding: 4px 8px;
  font-size: 11px;
}

/* ==================== Filters ==================== */
.filters {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.filter-input {
  flex: 1;
  min-width: 150px;
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 12px;
  outline: none;
}

.filter-input:focus {
  border-color: var(--focus-border);
}

.filter-select {
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.filter-select:focus {
  border-color: var(--focus-border);
}

.filter-tag {
  font-size: 11px;
  padding: 4px 10px;
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
  border-radius: 4px;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
}

/* ==================== Task List ==================== */
.task-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.task-item:hover {
  border-color: var(--focus-border);
}

.task-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.task-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.task-status-dot.status-pending { background: #3b82f6; }
.task-status-dot.status-progress { background: #8b5cf6; }
.task-status-dot.status-blocked { background: #f59e0b; }
.task-status-dot.status-completed { background: #22c55e; }

.task-content {
  flex: 1;
  min-width: 0;
}

.task-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-desc {
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: 8px;
}

.task-time {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  white-space: nowrap;
}

.tag.status-pending { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.tag.status-progress { background: rgba(139, 92, 246, 0.15); color: #8b5cf6; }
.tag.status-blocked { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.tag.status-completed { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.tag.priority-low { background: rgba(34, 197, 94, 0.1); color: #22c55e; }
.tag.priority-medium { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
.tag.priority-high { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.tag-assignee { background: rgba(99, 102, 241, 0.1); color: #6366f1; }

/* ==================== Dialog ==================== */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
  width: 400px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dialog h3 {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}

.dialog-input, .dialog-textarea {
  width: 100%;
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 13px;
  outline: none;
  font-family: inherit;
}

.dialog-input:focus, .dialog-textarea:focus {
  border-color: var(--focus-border);
}

.dialog-textarea {
  resize: vertical;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

/* ==================== Drawer ==================== */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: 480px;
  max-width: 90vw;
  background: var(--bg-primary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.drawer-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

.btn-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
}

.btn-close:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

/* ==================== Detail Sections ==================== */
.detail-section {
  margin-bottom: 14px;
}

.detail-section h5 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-color);
}

.detail-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.detail-title-row h4 {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
  word-break: break-word;
}

.detail-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 6px 0;
  line-height: 1.5;
}

.detail-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 8px 0;
}

.detail-info {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-secondary);
}

.detail-pre {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}

.action-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.action-select {
  font-size: 11px;
  padding: 4px 8px;
}

.edit-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.edit-actions {
  display: flex;
  gap: 6px;
}

/* ==================== Children ==================== */
.child-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--text-primary);
}

/* ==================== Comments ==================== */
.comment-item {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-color);
}

.comment-item:last-child {
  border-bottom: none;
}

.comment-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  margin-bottom: 4px;
}

.comment-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.comment-content {
  font-size: 12px;
  color: var(--text-primary);
  margin: 0;
  line-height: 1.5;
}

.comment-input-row {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

/* ==================== States ==================== */
.loading-state, .empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-secondary);
  font-size: 13px;
}

.error-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--error-fg, #ef4444);
  font-size: 13px;
}

.dialog-confirm {
  max-width: 360px;
}

.dialog-confirm p {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.5;
}

.empty-state-sm {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 8px 0;
}
</style>
