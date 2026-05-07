<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage } from '../api/vscode'
import { taskApi, jobApi } from '../utils/api'

const chatStore = useChatStore()

// ==================== 页面切换 ====================
const emit = defineEmits<{
  (e: 'navigate', page: string): void
}>()

// ==================== 任务/Job 计数 ====================
const taskCount = ref<number | null>(null)
const jobCount = ref<number | null>(null)
const countLoading = ref(false)

async function fetchCounts() {
  const sessionId = chatStore.sessionId
  if (!sessionId) return

  countLoading.value = true
  try {
    const [taskRes, jobRes] = await Promise.all([
      taskApi.getTasks({ session_id: sessionId, limit: 1 }),
      jobApi.getJobs({ session_id: sessionId, limit: 1 }),
    ])
    taskCount.value = taskRes.total ?? taskRes.tasks?.length ?? 0
    jobCount.value = jobRes.total ?? jobRes.jobs?.length ?? 0
  } catch (e) {
    // 静默失败，不阻塞侧栏
    console.warn('[ChatInfoSidebar] Failed to fetch counts:', e)
  } finally {
    countLoading.value = false
  }
}

onMounted(() => {
  fetchCounts()
})

// ==================== Session 统计 ====================
const stats = computed(() => {
  const msgs = chatStore.messages
  return {
    total: msgs.length,
    userMessages: msgs.filter(m => m.message_type === 'user_message' || m.role === 'user').length,
    agentResponses: msgs.filter(m => m.message_type === 'agent_response' || m.role === 'assistant').length,
    systemMessages: msgs.filter(m => m.message_type === 'system_message' || m.role === 'system').length,
    toolCalls: msgs.filter(m => m.message_type === 'tool_call').length,
    toolCallErrors: msgs.filter(m => m.message_type === 'tool_call' && (m.data?.status === false || m.data?.status === 'error')).length,
  }
})

// ==================== Runner 状态 ====================
const runnerInfo = computed(() => chatStore.runnerInfo)

const runnerStatusConfig: Record<string, { label: string; btnLabel: string }> = {
  alive: { label: '运行中', btnLabel: '停止进程' },
  starting: { label: '启动中', btnLabel: '...' },
  error: { label: '进程异常', btnLabel: '重启进程' },
  dead: { label: '已停止', btnLabel: '启动进程' },
}

function getRunnerConfig(status: string | undefined) {
  return runnerStatusConfig[status || 'dead'] || runnerStatusConfig.dead
}

function formatUptime(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function formatMemory(mb: number | undefined): string {
  if (!mb) return '-'
  if (mb > 1024) return `${(mb / 1024).toFixed(1)}GB`
  return `${Math.round(mb)}MB`
}

function handleRunnerAction() {
  if (chatStore.runnerActionLoading) return
  chatStore.runnerActionLoading = true
  const status = runnerInfo.value?.status
  if (status === 'alive') {
    postMessage({
      type: 'runnerAction',
      payload: { action: 'stop', sessionId: chatStore.sessionId },
    })
  } else {
    postMessage({
      type: 'runnerAction',
      payload: { action: 'restart', sessionId: chatStore.sessionId },
    })
  }
}

function handleRefreshRunner() {
  postMessage({
    type: 'fetchRunnerStatus',
    payload: { sessionId: chatStore.sessionId },
  })
}

// ==================== 侧栏状态 ====================
const isOpen = computed(() => chatStore.showRightSidebar)
</script>

<template>
  <div class="info-sidebar" :class="{ open: isOpen }">
    <div class="sidebar-header">
      <span class="sidebar-title">📊 Info</span>
      <button class="close-btn" @click="chatStore.toggleRightSidebar()">✕</button>
    </div>

    <div class="sidebar-content">
      <!-- ==================== Session Info ==================== -->
      <div class="panel">
        <div class="panel-title">Session Info</div>
        <div class="panel-body">
          <div class="info-row">
            <span class="info-label">Session ID</span>
            <span class="info-value mono" :title="chatStore.sessionId">{{ chatStore.sessionId || '未设置' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Total Messages</span>
            <span class="info-value">{{ stats.total }}</span>
          </div>
          <button class="nav-btn" @click="emit('navigate', 'tasks')">
            <span>📋</span>
            <span>任务</span>
            <span v-if="taskCount !== null" class="nav-badge">{{ taskCount }}</span>
          </button>
          <button class="nav-btn" @click="emit('navigate', 'jobs')">
            <span>⏰</span>
            <span>定时Job</span>
            <span v-if="jobCount !== null" class="nav-badge">{{ jobCount }}</span>
          </button>
        </div>
      </div>

      <!-- ==================== Runner Status ==================== -->
      <div class="panel">
        <div class="panel-title">
          <span>Runner Status</span>
          <button class="refresh-btn" @click="handleRefreshRunner" title="刷新">🔄</button>
        </div>
        <div class="panel-body">
          <div class="info-row">
            <span class="info-label">状态</span>
            <span class="status-tag" :class="'status-' + (runnerInfo?.status || 'dead')">
              {{ getRunnerConfig(runnerInfo?.status).label }}
            </span>
          </div>
          <div class="info-row">
            <span class="info-label">PID</span>
            <span class="info-value mono">{{ runnerInfo?.pid || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">运行时长</span>
            <span class="info-value">{{ formatUptime(runnerInfo?.uptime_seconds) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">CPU</span>
            <span class="info-value">{{ runnerInfo?.resource_usage?.cpu_percent ?? '-' }}%</span>
          </div>
          <div class="info-row">
            <span class="info-label">内存</span>
            <span class="info-value">{{ formatMemory(runnerInfo?.resource_usage?.memory_rss_mb) }}</span>
          </div>
          <div v-if="runnerInfo" class="runner-actions">
            <button
              class="action-btn"
              :class="[runnerInfo.status === 'alive' ? 'btn-danger' : 'btn-primary', { 'btn-loading': chatStore.runnerActionLoading }]"
              :disabled="chatStore.runnerActionLoading || runnerInfo.status === 'starting'"
              @click="handleRunnerAction"
            >
              <span v-if="chatStore.runnerActionLoading" class="btn-spinner"></span>
              {{ chatStore.runnerActionLoading ? '处理中...' : getRunnerConfig(runnerInfo.status).btnLabel }}
            </button>
          </div>
        </div>
      </div>

      <!-- ==================== Message Statistics ==================== -->
      <div class="panel">
        <div class="panel-title">Message Statistics</div>
        <div class="panel-body">
          <div class="stat-item">
            <span class="stat-dot dot-blue"></span>
            <span class="stat-label">User Messages</span>
            <span class="stat-value">{{ stats.userMessages }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-dot dot-green"></span>
            <span class="stat-label">Assistant Responses</span>
            <span class="stat-value">{{ stats.agentResponses }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-dot dot-gray"></span>
            <span class="stat-label">System Messages</span>
            <span class="stat-value">{{ stats.systemMessages }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-dot dot-purple"></span>
            <span class="stat-label">Tool Calls</span>
            <span class="stat-value">{{ stats.toolCalls }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-dot dot-red"></span>
            <span class="stat-label">Tool Call Errors</span>
            <span class="stat-value" :class="{ 'error-value': stats.toolCallErrors > 0 }">{{ stats.toolCallErrors }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.info-sidebar {
  width: 240px;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow-y: auto;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
}

.sidebar-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 4px;
  display: none;
}

.close-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.sidebar-content {
  flex: 1;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ==================== Navigation Buttons ==================== */
.nav-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 4px;
}

.nav-btn:hover {
  background: var(--bg-tertiary);
  border-color: var(--focus-border);
}

.nav-btn:last-child {
  margin-bottom: 0;
}

.nav-badge {
  margin-left: auto;
  background: var(--button-bg);
  color: var(--button-text);
  font-size: 10px;
  font-weight: 600;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

/* ==================== Panel ==================== */
.panel {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.refresh-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  border-radius: 3px;
}

.refresh-btn:hover {
  background: var(--bg-primary);
  color: var(--text-primary);
}

.panel-body {
  padding: 8px 10px;
}

/* ==================== Info Row ==================== */
.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 12px;
}

.info-label {
  color: var(--text-secondary);
}

.info-value {
  color: var(--text-primary);
  font-weight: 500;
}

.info-value.mono {
  font-family: var(--code-font-family);
  font-size: 11px;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ==================== Status Tag ==================== */
.status-tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
}

.status-alive {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success-fg);
}

.status-starting {
  background: rgba(234, 179, 8, 0.15);
  color: var(--warning-fg);
}

.status-error {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error-fg);
}

.status-dead {
  background: rgba(156, 163, 175, 0.15);
  color: var(--text-secondary);
}

/* ==================== Runner Actions ==================== */
.runner-actions {
  padding-top: 6px;
  border-top: 1px solid var(--border-color);
  margin-top: 4px;
}

.action-btn {
  width: 100%;
  border: none;
  border-radius: 4px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  text-align: center;
}

.btn-danger {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error-fg);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
}

.btn-primary:hover {
  background: var(--button-hover-bg);
}

.btn-loading {
  opacity: 0.7;
  cursor: not-allowed;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.btn-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== Stat Item ==================== */
.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  font-size: 12px;
}

.stat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-blue { background: #3b82f6; }
.dot-green { background: #22c55e; }
.dot-gray { background: #6b7280; }
.dot-purple { background: #a855f7; }
.dot-red { background: #ef4444; }

.stat-label {
  flex: 1;
  color: var(--text-secondary);
}

.stat-value {
  color: var(--text-primary);
  font-weight: 500;
  font-family: var(--code-font-family);
}

.stat-value.error-value {
  color: var(--error-fg);
  font-weight: 700;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .info-sidebar {
    position: fixed;
    top: 0;
    right: -240px;
    bottom: 0;
    z-index: 100;
    transition: right 0.2s ease;
    box-shadow: -2px 0 8px rgba(0, 0, 0, 0.2);
  }

  .info-sidebar.open {
    right: 0;
  }

  .close-btn {
    display: block;
  }
}
</style>
