<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores'
import { sessionApi, type SessionStats, type RunnerInfo } from '@/api/session'
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

// 启动轮询更新统计数据（每10秒）
const startStatsPolling = () => {
  if (statsPollingInterval) {
    clearInterval(statsPollingInterval)
  }
  statsPollingInterval = window.setInterval(() => {
    fetchStats()
    fetchJobAndTaskStats()
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

// 刷新 Runner 状态
const fetchRunnerStatus = () => {
  chatStore.fetchRunnerStatus()
}

// 重启 Runner
const handleRestartRunner = () => {
  chatStore.restartRunner()
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

onMounted(() => {
  if (chatStore.sessionId) {
    fetchStats()
    fetchJobAndTaskStats()
    startStatsPolling()
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

const totalMessagesFromApi = computed(() => {
  return stats.value?.total_messages || 0
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
    class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      flex: !chatStore.isMobile || chatStore.showRightSidebar,
      hidden: chatStore.isMobile && !chatStore.showRightSidebar,
      'fixed inset-x-0 top-[57px] bottom-0 z-40 bg-gray-50 p-3 rounded-none border-t lg:rounded-lg shadow-xl border':
        chatStore.isMobile && chatStore.showRightSidebar,
    }"
  >
    <div v-if="chatStore.isMobile && chatStore.showRightSidebar" class="flex justify-between items-center lg:hidden">
      <span class="text-sm font-semibold text-gray-700">Info</span>
      <el-button size="small" @click="chatStore.showRightSidebar = false"> ✕ </el-button>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="text-sm font-semibold text-gray-900 mb-3">Session Info</div>
      <div class="space-y-3 text-sm">
        <div class="flex justify-between">
          <span class="text-gray-700">Session ID:</span>
          <span class="font-mono text-xs truncate max-w-[150px] text-gray-800" :title="chatStore.sessionId">
            {{ chatStore.sessionId || '未设置' }}
          </span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-700">Total Messages:</span>
          <span class="font-mono text-gray-800">{{ totalMessagesFromApi }}</span>
        </div>
        <div
          class="flex justify-between items-center cursor-pointer hover:bg-gray-50 p-1 rounded"
          @click="router.push({ name: 'Jobs', query: { session_id: chatStore.sessionId } })"
          title="Click to view jobs for this session"
        >
          <span class="text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-orange-500" />
            Jobs:
          </span>
          <div class="flex items-center gap-2">
            <span v-if="jobTaskLoading" class="font-mono text-sm text-gray-500">
              <el-icon class="is-loading"><Loading /></el-icon>
            </span>
            <span v-else class="font-mono text-sm text-gray-800">{{ jobCount }}</span>
          </div>
        </div>
        <div
          class="flex justify-between items-center cursor-pointer hover:bg-gray-50 p-1 rounded"
          @click="router.push({ name: 'Tasks', query: { session_id: chatStore.sessionId } })"
          title="Click to view tasks for this session"
        >
          <span class="text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-indigo-500" />
            Tasks:
          </span>
          <div class="flex items-center gap-2">
            <span v-if="jobTaskLoading" class="font-mono text-sm text-gray-500">
              <el-icon class="is-loading"><Loading /></el-icon>
            </span>
            <span v-else class="font-mono text-sm text-gray-800">{{ taskCount }}</span>
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

    <!-- Runner 状态面板 -->
    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-semibold text-gray-900">Runner Status</div>
        <el-button size="small" circle :loading="runnerLoading" @click="fetchRunnerStatus">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
      <div v-if="runnerLoading && !runnerInfo" class="flex justify-center py-4">
        <el-icon class="is-loading"><Loading /></el-icon>
      </div>
      <div v-else class="space-y-2 text-sm">
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
        <div v-if="runnerInfo?.status === 'error'" class="pt-2">
          <el-button type="danger" size="small" :loading="restarting" @click="handleRestartRunner">
            重启进程
          </el-button>
        </div>
        <div v-else-if="runnerInfo && runnerInfo.status !== 'alive'" class="pt-2">
          <el-button type="warning" size="small" :loading="restarting" @click="handleRestartRunner">
            启动进程
          </el-button>
        </div>
      </div>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-semibold text-gray-900">Message Statistics</div>
        <el-tooltip content="Auto-refresh every 30s" placement="top">
          <el-button size="small" circle :loading="statsLoading" @click="fetchStats">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <div class="space-y-2">
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-blue-500" />
            User Messages
          </span>
          <span class="font-mono text-sm text-gray-800">{{ userMessagesFromApi }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-500" />
            Assistant Responses
          </span>
          <span class="font-mono text-sm text-gray-800">{{ assistantMessagesFromApi }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-gray-500" />
            System Messages
          </span>
          <span class="font-mono text-sm text-gray-800">{{ systemMessagesFromApi }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-red-500" />
            Tool Call Errors
          </span>
          <span
            class="font-mono text-sm text-gray-800"
            :class="{ 'text-red-600 font-bold': toolCallErrorsFromApi > 0 }"
          >
            {{ toolCallErrorsFromApi }}
          </span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-700 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-purple-500" />
            Tool Calls
          </span>
          <span class="font-mono text-sm text-gray-800">{{ toolCallsFromApi }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
