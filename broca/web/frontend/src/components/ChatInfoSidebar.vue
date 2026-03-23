<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '@/stores'
import { sessionApi, type SessionStats } from '@/api/session'
import { Loading, Refresh } from '@element-plus/icons-vue'

const chatStore = useChatStore()

// 统计数据（从API获取）
const stats = ref<SessionStats | null>(null)
const statsLoading = ref(false)
let statsPollingInterval: number | null = null

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

// 启动轮询更新统计数据（每30秒）
const startStatsPolling = () => {
  if (statsPollingInterval) {
    clearInterval(statsPollingInterval)
  }
  statsPollingInterval = window.setInterval(() => {
    fetchStats()
  }, 30000)
}

// 停止轮询
const stopStatsPolling = () => {
  if (statsPollingInterval) {
    clearInterval(statsPollingInterval)
    statsPollingInterval = null
  }
}

// 监听sessionId变化，重新获取统计数据
watch(() => chatStore.sessionId, (newSessionId, oldSessionId) => {
  if (newSessionId && newSessionId !== oldSessionId) {
    fetchStats()
  }
}, { immediate: true })

onMounted(() => {
  // 页面加载时获取统计数据
  if (chatStore.sessionId) {
    fetchStats()
    startStatsPolling()
  }
})

onUnmounted(() => {
  stopStatsPolling()
})

// 从API统计数据中提取各类型消息数
const userMessagesFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  // 查找user_message类型
  return stats.value.messages_by_type['MessageType.USER_MESSAGE'] || 
         stats.value.messages_by_type['USER_MESSAGE'] ||
         0
})

const assistantMessagesFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  // 查找agent_response类型
  return stats.value.messages_by_type['MessageType.AGENT_RESPONSE'] || 
         stats.value.messages_by_type['AGENT_RESPONSE'] ||
         0
})

const systemMessagesFromApi = computed(() => {
  if (!stats.value?.messages_by_type) return 0
  // 查找系统相关类型：system_message, agent_system_message等
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
  // 查找tool_call类型
  return stats.value.messages_by_type['MessageType.TOOL_CALL'] || 
         stats.value.messages_by_type['TOOL_CALL'] ||
         0
})

// 从API获取的工具调用错误数量
const toolCallErrorsFromApi = computed(() => {
  return stats.value?.tool_call_errors || 0
})

// 消息总数（使用API数据）
const totalMessagesFromApi = computed(() => {
  return stats.value?.total_messages || 0
})
</script>

<template>
  <div 
    class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      'flex': !chatStore.isMobile || chatStore.showRightSidebar,
      'hidden': chatStore.isMobile && !chatStore.showRightSidebar,
      'absolute inset-x-2 top-20 bottom-4 z-40 bg-gray-50 p-3 rounded-lg shadow-xl border': chatStore.isMobile && chatStore.showRightSidebar
    }"
  >
    <div v-if="chatStore.isMobile && chatStore.showRightSidebar" class="flex justify-between items-center lg:hidden">
      <span class="text-sm font-semibold text-gray-700">Info</span>
      <el-button size="small" @click="chatStore.showRightSidebar = false">✕</el-button>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="text-sm font-semibold text-gray-900 mb-3">Session Info</div>
      <div class="space-y-3 text-sm">
        <div class="flex justify-between">
          <span class="text-gray-500">Session:</span>
          <span class="font-mono text-xs truncate max-w-[150px]" :title="chatStore.sessionId">
            {{ chatStore.sessionId || '未设置' }}
          </span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-500">Agent:</span>
          <span class="font-mono text-xs">{{ chatStore.agentId }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-500">Status:</span>
          <el-tag :type="chatStore.connected ? 'success' : 'info'" size="small">{{ chatStore.statusText }}</el-tag>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-500">Total Messages:</span>
          <span class="font-mono">{{ totalMessagesFromApi }}</span>
        </div>
        <div v-if="statsLoading" class="flex justify-between">
          <span class="text-gray-500">Loading stats...</span>
          <el-icon class="is-loading"><Loading /></el-icon>
        </div>
      </div>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-semibold text-gray-900">Message Statistics</div>
        <el-tooltip content="Auto-refresh every 30s" placement="top">
          <el-button size="small" circle @click="fetchStats" :loading="statsLoading">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <div class="space-y-2">
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-blue-500"></span>
            User Messages
          </span>
          <span class="font-mono text-sm">{{ userMessagesFromApi }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-500"></span>
            Assistant Responses
          </span>
          <span class="font-mono text-sm">{{ assistantMessagesFromApi }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-gray-500"></span>
            System Messages
          </span>
          <span class="font-mono text-sm">{{ systemMessagesFromApi }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-red-500"></span>
            Tool Call Errors
          </span>
          <span class="font-mono text-sm" :class="{'text-red-600 font-bold': toolCallErrorsFromApi > 0}">
            {{ toolCallErrorsFromApi }}
          </span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-purple-500"></span>
            Tool Calls
          </span>
          <span class="font-mono text-sm">{{ toolCallsFromApi }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
