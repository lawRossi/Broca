<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage, onMessage } from '../api/vscode'
import { taskApi, jobApi } from '../utils/api'
import type { SessionStats } from '../types'

const chatStore = useChatStore()

// ==================== 页面切换 ====================
const emit = defineEmits<{
  (e: 'navigate', page: string): void
}>()

// ==================== 任务/Job 计数 ====================
const taskCount = ref<number | null>(null)
const jobCount = ref<number | null>(null)
const countLoading = ref(false)

// ==================== Workspace ====================
const workspace = ref('')
const workspaceLoading = ref(false)

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

async function fetchWorkspace() {
  const sessionId = chatStore.sessionId
  if (!sessionId) {
    workspace.value = ''
    return
  }

  workspaceLoading.value = true
  postMessage({
    type: 'getSession',
    payload: { sessionId },
  })
}

// ==================== Session 统计（通过 API 获取，与 Web 版一致） ====================
const stats = ref<SessionStats | null>(null)
const statsLoading = ref(false)
let statsPollingTimer: ReturnType<typeof setInterval> | null = null
let countsPollingTimer: ReturnType<typeof setInterval> | null = null
let removeMessageListener: (() => void) | null = null

async function fetchStats() {
  const sessionId = chatStore.sessionId
  if (!sessionId) return

  statsLoading.value = true
  postMessage({
    type: 'fetchSessionStats',
    payload: { sessionId },
  })
  // 不在这里设置 statsLoading=false，等待响应消息
}

function startStatsPolling() {
  stopStatsPolling()
  // 每 30 秒轮询一次，仅在 runner 运行时才拉取数据
  statsPollingTimer = setInterval(() => {
    if (chatStore.runnerAlive) {
      fetchStats()
    }
  }, 30000)
}

function stopStatsPolling() {
  if (statsPollingTimer) {
    clearInterval(statsPollingTimer)
    statsPollingTimer = null
  }
}

function startCountsPolling() {
  stopCountsPolling()
  countsPollingTimer = setInterval(() => {
    if (chatStore.runnerAlive) {
      fetchCounts()
    }
  }, 30000)
}

function stopCountsPolling() {
  if (countsPollingTimer) {
    clearInterval(countsPollingTimer)
    countsPollingTimer = null
  }
}


const userMessagesFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  return stats.value.messages_by_type['MessageType.USER_MESSAGE'] || stats.value.messages_by_type['USER_MESSAGE'] || 0
})

const assistantMessagesFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  return (
    stats.value.messages_by_type['MessageType.AGENT_RESPONSE'] || stats.value.messages_by_type['AGENT_RESPONSE'] || 0
  )
})

const systemMessagesFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  let count = 0
  const typeMap = stats.value.messages_by_type
  count += typeMap['MessageType.SYSTEM_MESSAGE'] || typeMap['SYSTEM_MESSAGE'] || 0
  count += typeMap['MessageType.AGENT_SYSTEM_MESSAGE'] || typeMap['AGENT_SYSTEM_MESSAGE'] || 0
  count += typeMap['MessageType.COMMAND'] || typeMap['COMMAND'] || 0
  count += typeMap['MessageType.COMMAND_RESULT'] || typeMap['COMMAND_RESULT'] || 0
  count += typeMap['MessageType.PERMISSION_REQUEST'] || typeMap['PERMISSION_REQUEST'] || 0
  count += typeMap['MessageType.PERMISSION_RESPONSE'] || typeMap['PERMISSION_RESPONSE'] || 0
  count += typeMap['MessageType.SUBSCRIBE'] || typeMap['SUBSCRIBE'] || 0
  count += typeMap['MessageType.UNSUBSCRIBE'] || typeMap['UNSUBSCRIBE'] || 0
  count += typeMap['MessageType.BROADCAST'] || typeMap['BROADCAST'] || 0
  count += typeMap['MessageType.TURN_START'] || typeMap['TURN_START'] || 0
  count += typeMap['MessageType.TURN_END'] || typeMap['TURN_END'] || 0
  return count
})

const toolCallsFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  return stats.value.messages_by_type['MessageType.TOOL_CALL'] || stats.value.messages_by_type['TOOL_CALL'] || 0
})

const toolCallErrorsFromApi = computed(() => {
  return stats.value?.tool_call_errors || 0
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
  if (h > 0) return h + '小时' + m + '分钟'
  return m + '分钟'
}

function formatMemory(mb: number | undefined): string {
  if (!mb) return '-'
  if (mb > 1024) return `${(mb / 1024).toFixed(1)}GB`
  return `${Math.round(mb)}MB`
}

function handleStopRunner() {
  if (chatStore.runnerActionLoading) return
  chatStore.runnerActionLoading = true
  postMessage({ type: 'runnerAction', payload: { action: 'stop' } })
}

function handleRestartRunner() {
  if (chatStore.runnerActionLoading) return
  chatStore.runnerActionLoading = true
  postMessage({ type: 'runnerAction', payload: { action: 'start' } })
}

function handleRefreshRunner() {
  postMessage({
    type: 'fetchRunnerStatus',
    payload: { sessionId: chatStore.sessionId },
  })
}

function handleRefreshStats() {
  fetchStats()
}

const copyFeedback = ref(false)

function copySessionId() {
  const id = chatStore.sessionId
  if (!id) return
  navigator.clipboard.writeText(id).then(() => {
    copyFeedback.value = true
    setTimeout(() => {
      copyFeedback.value = false
    }, 1500)
  })
}

// ==================== 侧栏状态 ====================
const isOpen = computed(() => chatStore.showRightSidebar)

onMounted(() => {
  fetchCounts()
  startCountsPolling()

  // 监听 sessionStats 和 session 响应
  removeMessageListener = onMessage((data: any) => {
    if (data.type === 'sessionStats') {
      stats.value = data.payload
      statsLoading.value = false
    } else if (data.type === 'session') {
      workspace.value = data.payload?.workspace || ''
      workspaceLoading.value = false
    }
  })

  // 初始获取统计
  if (chatStore.sessionId) {
    fetchStats()
    fetchWorkspace()
    // stats 轮询由 runner 状态 watcher 控制启停
  }
})

// 监听 Runner 状态变化，控制 stats 轮询启停
watch(
  () => chatStore.runnerInfo?.status,
  (newStatus) => {
    if (newStatus === 'alive') {
      startStatsPolling()
    } else {
      stopStatsPolling()
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  stopStatsPolling()
  stopCountsPolling()
  if (removeMessageListener) {
    removeMessageListener()
    removeMessageListener = null
  }
})
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
          <div class="session-id-section">
            <span class="info-label">Session ID</span>
            <div class="session-id-group">
              <span class="session-id-text mono" :title="chatStore.sessionId">{{ chatStore.sessionId }}</span>
              <button class="copy-btn" :class="{ 'copied': copyFeedback }" @click="copySessionId" :title="copyFeedback ? '已复制' : '复制 Session ID'">{{ copyFeedback ? '✓' : '📋' }}</button>
            </div>
          </div>
          <div class="workspace-section">
            <span class="info-label">Workspace</span>
            <div class="session-id-group">
              <span class="session-id-text mono" :title="workspace">{{ workspace || '未设置' }}</span>
            </div>
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
          <div class="runner-actions">
            <div v-if="runnerInfo?.status === 'alive'">
              <button
                class="action-btn btn-danger"
                :disabled="chatStore.runnerActionLoading"
                @click="handleStopRunner"
              >
                <span v-if="chatStore.runnerActionLoading" class="btn-spinner"></span>
                {{ chatStore.runnerActionLoading ? '处理中...' : '停止进程' }}
              </button>
            </div>
            <div v-else-if="runnerInfo?.status === 'error'">
              <button
                class="action-btn btn-danger"
                :disabled="chatStore.runnerActionLoading"
                @click="handleRestartRunner"
              >
                <span v-if="chatStore.runnerActionLoading" class="btn-spinner"></span>
                {{ chatStore.runnerActionLoading ? '处理中...' : '重启进程' }}
              </button>
            </div>
            <div v-else-if="runnerInfo && runnerInfo.status !== 'starting'">
              <button
                class="action-btn btn-primary"
                :disabled="chatStore.runnerActionLoading"
                @click="handleRestartRunner"
              >
                <span v-if="chatStore.runnerActionLoading" class="btn-spinner"></span>
                {{ chatStore.runnerActionLoading ? '处理中...' : '启动进程' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== Message Statistics ==================== -->
      <div class="panel">
        <div class="panel-title">
          <span>Message Statistics</span>
        </div>
        <div class="panel-body">
          <div class="stat-item">
            <span class="stat-label">User Messages</span>
            <span class="stat-value">{{ userMessagesFromApi }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Assistant Responses</span>
            <span class="stat-value">{{ assistantMessagesFromApi }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">System Messages</span>
            <span class="stat-value">{{ systemMessagesFromApi }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Tool Calls</span>
            <span class="stat-value">{{ toolCallsFromApi }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Tool Call Errors</span>
            <span class="stat-value" :class="{ 'error-value': toolCallErrorsFromApi > 0 }">{{ toolCallErrorsFromApi }}</span>
          </div>
          <div v-if="statsLoading" class="stat-loading">
            <span class="loading-spinner"></span>
            <span class="loading-text">刷新中...</span>
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

/* ==================== Session ID ==================== */
.session-id-group {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
  justify-content: flex-end;
}

.session-id-text {
  font-family: var(--code-font-family);
  font-size: 11px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.copy-btn {
  background: none;
  border: 1px solid var(--border-color);
  border-radius: 3px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  padding: 0 3px;
  line-height: 18px;
  flex-shrink: 0;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.copy-btn:hover {
  opacity: 1;
  background: var(--bg-tertiary);
}

.copy-btn.copied {
  opacity: 1;
  background: rgba(34, 197, 94, 0.15);
  border-color: rgba(34, 197, 94, 0.4);
  color: #22c55e;
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
  width: auto;
  border: none;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 11px;
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

/* ==================== Stat Loading ==================== */
.stat-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  font-size: 11px;
  color: var(--text-secondary);
}

.loading-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid var(--border-color);
  border-top-color: var(--text-secondary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

.loading-text {
  color: var(--text-secondary);
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
