<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores'
import { sessionApi, type SessionStats} from '@/api/session'
import { jobApi } from '@/api/job'
import { taskApi } from '@/api/task'
import { Loading, Refresh } from '@element-plus/icons-vue'

const router = useRouter()
const chatStore = useChatStore()

// 统计数据（从API获取）
const stats = ref<SessionStats | null>(null)
const statsLoading = ref(false)
let statsPollingInterval: number | null = null

// Job和Task统计
const jobCount = ref(0)
const taskCount = ref(0)
const jobTaskLoading = ref(false)

// Workspace
const workspace = ref('')
const workspaceLoading = ref(false)

// 获取统计数据
const fetchStats = async () => {
  if (!chatStore.sessionId) {
    return
  }

  try {
    statsLoading.value = true
    const data = await sessionApi.getSessionStats(chatStore.sessionId)
    stats.value = data
  } catch (error) {
    console.error('Failed to fetch session stats:', error)
    // 静默失败，不影响其他功能
  } finally {
    statsLoading.value = false
  }
}

// 获取Job和Task统计
const fetchJobAndTaskStats = async () => {
  if (!chatStore.sessionId) {
    return
  }

  try {
    jobTaskLoading.value = true

    // 并行获取job和task统计
    const [jobsRes, tasksRes] = await Promise.all([
      jobApi.getJobs({
        session_id: chatStore.sessionId,
        limit: 1, // 只需要总数，不需要具体数据
      }),
      taskApi.getTasks({
        session_id: chatStore.sessionId,
        limit: 1, // 只需要总数，不需要具体数据
      }),
    ])

    jobCount.value = jobsRes.total
    taskCount.value = tasksRes.total
  } catch (error) {
    console.error('Failed to fetch job and task stats:', error)
    // 静默失败，不影响其他功能
  } finally {
    jobTaskLoading.value = false
  }
}

// 获取 Workspace
const fetchWorkspace = async () => {
  if (!chatStore.sessionId) {
    workspace.value = ''
    return
  }

  try {
    workspaceLoading.value = true
    const data = await sessionApi.getSession(chatStore.sessionId)
    workspace.value = data.workspace || ''
  } catch (error) {
    console.error('Failed to fetch workspace:', error)
    workspace.value = ''
  } finally {
    workspaceLoading.value = false
  }
}

// 启动轮询更新统计数据（每10秒）
const startStatsPolling = () => {
  if (statsPollingInterval) {
    clearInterval(statsPollingInterval)
  }
  statsPollingInterval = window.setInterval(() => {
    // 仅在 runner 进程运行时才拉取数据
    if (chatStore.runnerAlive) {
      fetchStats()
      fetchJobAndTaskStats()
    }
  }, 10000)
}

// 停止轮询
const stopStatsPolling = () => {
  if (statsPollingInterval) {
    clearInterval(statsPollingInterval)
    statsPollingInterval = null
  }
}

// Runner 状态（从 chatStore 获取）
const runnerInfo = computed(() => chatStore.runnerInfo)
const runnerLoading = computed(() => chatStore.runnerLoading)
const restarting = computed(() => chatStore.restartingRunner)
const stopping = computed(() => chatStore.stoppingRunner)

// 刷新 Runner 状态
const fetchRunnerStatus = () => {
  chatStore.fetchRunnerStatus()
}

// 重启 Runner
const handleRestartRunner = () => {
  chatStore.restartRunner()
}

// 停止 Runner
const handleStopRunner = () => {
  chatStore.stopRunner()
}

// 监听 sessionId 变化，重新获取统计数据
watch(
  () => chatStore.sessionId,
  (newSessionId, oldSessionId) => {
    if (newSessionId && newSessionId !== oldSessionId) {
      fetchStats()
      fetchJobAndTaskStats()
    }
  },
  { immediate: true }
)

// 监听 Runner 状态变化，控制轮询启停
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

onMounted(() => {
  if (chatStore.sessionId) {
    fetchStats()
    fetchJobAndTaskStats()
    fetchWorkspace()
    // 轮询由 runner 状态 watcher 控制启停
  }
})

onUnmounted(() => {
  stopStatsPolling()
})

// 格式化运行时长
const formatUptime = (seconds: number | undefined): string => {
  if (!seconds || seconds <= 0) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}小时${m}分钟`
  return `${m}分钟`
}

// 格式化内存
const formatMemory = (mb: number | undefined): string => {
  if (!mb) return '-'
  if (mb > 1024) return `${(mb / 1024).toFixed(1)}GB`
  return `${Math.round(mb)}MB`
}

// 从API统计数据中提取各类型消息数
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

const toolCallsFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  return stats.value.messages_by_type['MessageType.TOOL_CALL'] || stats.value.messages_by_type['TOOL_CALL'] || 0
})

const toolCallErrorsFromApi = computed(() => {
  return stats.value?.tool_call_errors || 0
})

// Runner 状态显示配置
const runnerStatusConfig: Record<string, { type: string; label: string }> = {
  alive: { type: 'success', label: '运行中' },
  starting: { type: 'warning', label: '启动中' },
  error: { type: 'danger', label: '进程异常' },
  dead: { type: 'info', label: '已停止' },
  none: { type: 'info', label: '未运行' },
}

const getRunnerConfig = (status: string | undefined) => {
  return runnerStatusConfig[status || 'none'] || runnerStatusConfig.none
}
</script>

<template>
  <div
    class="col-span-10 lg:col-span-2 flex-col gap-2 overflow-y-auto pr-1"
    :class="{
      flex: !chatStore.isMobile || chatStore.showRightSidebar,
      hidden: chatStore.isMobile && !chatStore.showRightSidebar,
      'fixed inset-x-0 top-[57px] bottom-0 z-40 bg-gray-50 p-3 rounded-none border-t lg:rounded-lg shadow-xl border':
        chatStore.isMobile && chatStore.showRightSidebar,
    }"
  >
    <div class="bg-white rounded-lg border p-2 sm:p-3 shadow hover:shadow-md transition-shadow duration-200">
      <div class="text-sm font-semibold text-gray-900 mb-2">Session Info</div>
      <div class="bg-gradient-to-r from-gray-50 to-blue-50 rounded-lg p-2 border border-gray-100">
        <div class="space-y-1.5 text-sm">
          <div>
            <div class="text-gray-700 mb-1">Session ID:</div>
            <div class="font-mono text-xs truncate text-gray-800 break-all" :title="chatStore.sessionId">
              {{ chatStore.sessionId || '未设置' }}
            </div>
          </div>
          <div>
            <div class="text-gray-700 mb-1">Workspace:</div>
            <div class="font-mono text-xs truncate text-gray-800 break-all" :title="workspace">
              {{ workspace || '未设置' }}
            </div>
          </div>
          <div
            class="flex justify-between items-center cursor-pointer hover:bg-gray-50 py-0.5 px-1 rounded"
            @click="router.push({ name: 'Tasks', query: { session_id: chatStore.sessionId } })"
            title="Click to view tasks for this session"
          >
            <span class="text-gray-700">
              Agent Task:
            </span>
            <div class="flex items-center gap-2">
              <span v-if="jobTaskLoading" class="font-mono text-sm text-gray-500">
                <el-icon class="is-loading"><Loading /></el-icon>
              </span>
              <span v-else class="font-mono text-sm text-gray-800">{{ taskCount }}</span>
            </div>
          </div>
          <div
            class="flex justify-between items-center cursor-pointer hover:bg-gray-50 py-0.5 px-1 rounded"
            @click="router.push({ name: 'Jobs', query: { session_id: chatStore.sessionId } })"
            title="Click to view jobs for this session"
          >
            <span class="text-gray-700">
              后台Job:
            </span>
            <div class="flex items-center gap-2">
              <span v-if="jobTaskLoading" class="font-mono text-sm text-gray-500">
                <el-icon class="is-loading"><Loading /></el-icon>
              </span>
              <span v-else class="font-mono text-sm text-gray-800">{{ jobCount }}</span>
            </div>
          </div>
          <div v-if="statsLoading" class="flex justify-between">
            <span class="text-gray-700">Loading stats...</span>
            <el-icon class="is-loading">
              <Loading />
            </el-icon>
          </div>
        </div>
      </div>
    </div>

    <!-- Runner 状态面板 -->
    <div class="bg-white rounded-lg border p-2 sm:p-3 shadow hover:shadow-md transition-shadow duration-200">
      <div class="flex items-center justify-between mb-2">
        <div class="text-sm font-semibold text-gray-900">Runner Status</div>
        <el-button size="small" circle :loading="runnerLoading" @click="fetchRunnerStatus">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
      <div v-if="runnerLoading && !runnerInfo" class="flex justify-center py-4">
        <el-icon class="is-loading"><Loading /></el-icon>
      </div>
      <div v-else class="bg-gradient-to-r from-gray-50 to-blue-50 rounded-lg p-2 border border-gray-100">
        <div class="space-y-1.5 text-sm">
          <div class="flex justify-between items-center">
            <span class="text-gray-700">状态</span>
            <el-tag :type="getRunnerConfig(runnerInfo?.status).type" size="small">
              {{ getRunnerConfig(runnerInfo?.status).label }}
            </el-tag>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-700">PID</span>
            <span class="font-mono text-gray-800">{{ runnerInfo?.pid || '-' }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-700">运行时长</span>
            <span class="text-gray-800">{{ formatUptime(runnerInfo?.uptime_seconds) }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-700">CPU</span>
            <span class="text-gray-800">{{ runnerInfo?.resource_usage?.cpu_percent ?? '-' }}%</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-700">内存</span>
            <span class="text-gray-800">{{ formatMemory(runnerInfo?.resource_usage?.memory_rss_mb) }}</span>
          </div>
          <div v-if="runnerInfo?.status === 'alive'" class="pt-2 flex gap-2">
            <el-button type="danger" size="small" :loading="stopping" @click="handleStopRunner">
              停止进程
            </el-button>
          </div>
          <div v-else-if="runnerInfo?.status === 'error'" class="pt-2">
            <el-button type="danger" size="small" :loading="restarting" @click="handleRestartRunner">
              重启进程
            </el-button>
          </div>
          <div v-else-if="runnerInfo && runnerInfo.status !== 'starting'" class="pt-2">
            <el-button type="warning" size="small" :loading="restarting" @click="handleRestartRunner">
              启动进程
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="bg-white rounded-lg border p-2 sm:p-3 shadow hover:shadow-md transition-shadow duration-200">
      <div class="flex items-center justify-between mb-2">
        <div class="text-sm font-semibold text-gray-900">Message Statistics</div>
      </div>
      <div class="bg-gradient-to-r from-gray-50 to-blue-50 rounded-lg p-2 border border-gray-100">
        <div class="space-y-1.5">
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-700 flex items-center gap-2">
              User Messages
            </span>
            <span class="font-mono text-sm text-gray-800">{{ userMessagesFromApi }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-700 flex items-center gap-2">
              Assistant Responses
            </span>
            <span class="font-mono text-sm text-gray-800">{{ assistantMessagesFromApi }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-700 flex items-center gap-2">
              Tool Calls
            </span>
            <span class="font-mono text-sm text-gray-800">{{ toolCallsFromApi }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-700 flex items-center gap-2">
              Tool Call Errors
            </span>
            <span
              class="font-mono text-sm text-gray-800"
              :class="{ 'text-red-600 font-bold': toolCallErrorsFromApi > 0 }"
            >
              {{ toolCallErrorsFromApi }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
