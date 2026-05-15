<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch, computed } from 'vue'
import { useChatStore, useAgentStore } from '@/stores'
import type { Agent } from '@/stores/agent'
import { ElIcon, ElTooltip, ElTag, ElButton, ElDialog } from 'element-plus'
import {
  User,
  Document,
  Search,
  List,
  PieChart,
  QuestionFilled,
  Loading,
  CircleCheck,
  CircleClose,
  Refresh,
  Setting,
  InfoFilled,
  ChatDotRound,
  TrendCharts,
  DataAnalysis,
} from '@element-plus/icons-vue'
import { StarFilled } from '@element-plus/icons-vue'

const chatStore = useChatStore()
const agentStore = useAgentStore()

const showConfigDialog = ref(false)
const loading = ref(false)
const selectedAgent = ref<Agent | null>(null)
const autoRefreshInterval = ref<number | null>(null)
const lastRefreshTime = ref<Date>(new Date())

// 使用 computed 从 agentStore 获取 agents 列表
const agents = computed(() => agentStore.agents)

// 使用 computed 从 agentStore 获取选中的 agent 配置
const selectedAgentConfig = computed(() => agentStore.selectedAgentConfig)
const configLoading = computed(() => agentStore.loading)

const statusColors: Record<string, string> = {
  idle: 'success',
  running: 'primary',
  connecting: 'warning',
  disconnected: 'danger',
}

const typeIcons: Record<string, any> = {
  assistant: User,
  code_assistant: Document,
  research_assistant: Search,
  task_manager: List,
  data_analyst: PieChart,
}

const typeColors: Record<string, string> = {
  assistant: 'blue',
  code_assistant: 'green',
  research_assistant: 'orange',
  task_manager: 'purple',
  data_analyst: 'cyan',
}

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'idle':
      return CircleCheck
    case 'running':
      return Loading
    case 'connecting':
      return Loading
    case 'disconnected':
      return CircleClose
    default:
      return QuestionFilled
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'idle':
      return '空闲'
    case 'running':
      return '运行中'
    case 'connecting':
      return '连接中'
    case 'disconnected':
      return '断开连接'
    default:
      return '未知'
  }
}

const getTypeIcon = (type: string) => {
  return typeIcons[type] || QuestionFilled
}

const getTypeColor = (type: string) => {
  return typeColors[type] || 'gray'
}

const refreshAgents = async () => {
  if (!chatStore.sessionId) return
  loading.value = true
  try {
    await agentStore.fetchAgents(chatStore.sessionId)
    lastRefreshTime.value = new Date()
  } finally {
    loading.value = false
  }
}

// 自动刷新相关
const startAutoRefresh = (intervalMs: number = 10000) => {
  if (autoRefreshInterval.value) {
    stopAutoRefresh()
  }
  // 立即刷新一次
  if (chatStore.sessionId) {
    refreshAgents()
  }
  // 设置定时器
  autoRefreshInterval.value = window.setInterval(() => {
    if (chatStore.sessionId && !loading.value) {
      refreshAgents()
    }
  }, intervalMs)
}

const stopAutoRefresh = () => {
  if (autoRefreshInterval.value) {
    window.clearInterval(autoRefreshInterval.value)
    autoRefreshInterval.value = null
  }
}

const handleAgentClick = (agent: Agent) => {
  selectedAgent.value = agent
  // 使用 agentStore 的 selectAgent 方法来获取配置
  if (chatStore.sessionId) {
    agentStore.selectAgent(agent.agent_id, chatStore.sessionId)
  }
  showConfigDialog.value = true
}

const closeConfigDialog = () => {
  showConfigDialog.value = false
  selectedAgent.value = null
  agentStore.selectedAgentConfig = null
}

// 刷新配置
const refreshConfig = async () => {
  if (!selectedAgent.value || !chatStore.sessionId) return
  await agentStore.fetchAgentConfig(chatStore.sessionId, selectedAgent.value.agent_id)
}

// 发送消息给选中的 Agent
const sendMessageToAgent = () => {
  if (!selectedAgent.value) return
  const agentName = selectedAgent.value.name || selectedAgent.value.agent_id?.slice(0, 8) || 'agent'
  chatStore.input = `@${agentName} `
  closeConfigDialog()
}

// 监听 session 变化，自动刷新 agents
watch(
  () => chatStore.sessionId,
  (newSessionId) => {
    if (newSessionId) {
      // 启动自动刷新（10秒间隔）
      startAutoRefresh(10000)
    } else {
      // 停止自动刷新
      stopAutoRefresh()
    }
  }
)

onMounted(() => {
  if (chatStore.sessionId) {
    // 启动自动刷新（10秒间隔）
    startAutoRefresh(10000)
  }
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div
    class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      flex: !chatStore.isMobile || chatStore.showLeftSidebar,
      hidden: chatStore.isMobile && !chatStore.showLeftSidebar,
      'fixed inset-x-0 top-[57px] bottom-0 z-40 bg-gray-50 p-3 rounded-none border-t lg:rounded-lg shadow-xl border':
        chatStore.isMobile && chatStore.showLeftSidebar,
    }"
  >
    <!-- 移动端标题 -->
    <div
      v-if="chatStore.isMobile && chatStore.showLeftSidebar"
      class="flex justify-between items-center lg:hidden mb-4"
    >
      <span class="text-sm font-semibold text-gray-700">Session Agents</span>
      <el-button size="small" @click="chatStore.showLeftSidebar = false"> ✕ </el-button>
    </div>

    <!-- Agent面板标题 -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-gray-900">Session Agents</h3>
        <el-tooltip content="点击Agent查看详情，使用 @agent名称 发送消息给指定agent" placement="top">
          <el-icon :size="14" class="text-gray-400 cursor-help">
            <InfoFilled />
          </el-icon>
        </el-tooltip>
        <el-tooltip v-if="autoRefreshInterval" content="自动刷新已开启 (30秒)" placement="top">
          <div class="flex items-center gap-1">
            <div class="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            <span class="text-[10px] text-gray-500">自动</span>
          </div>
        </el-tooltip>
      </div>
      <el-button
        size="small"
        :icon="Refresh"
        :loading="loading"
        class="!p-1 !h-6 !w-6"
        :disabled="!chatStore.sessionId"
        @click="refreshAgents"
      />
    </div>

    <!-- Agent列表 -->
    <div class="space-y-3">
      <div
        v-for="agent in agents"
        :key="agent.agent_id"
        class="bg-white rounded-lg border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 cursor-pointer"
        :class="{
          'ring-2 ring-blue-500': agentStore.currentAgentId === agent.agent_id,
          'ring-2 ring-yellow-500': agent.role === 'main_agent' || agent.role === 'main-agent',
        }"
        @click="handleAgentClick(agent)"
      >
        <!-- Agent 头部：名称、类型、状态 -->
        <div class="flex items-start justify-between mb-3">
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <div class="relative">
              <el-icon :size="20" :color="getTypeColor(agent.type || 'assistant')">
                <component :is="getTypeIcon(agent.type || 'assistant')" />
              </el-icon>
              <el-icon
                v-if="agent.role === 'main_agent' || agent.role === 'main-agent'"
                :size="10"
                class="absolute -top-1 -right-1 text-yellow-500"
                title="Main Agent (默认)"
              >
                <StarFilled />
              </el-icon>
            </div>
            <div class="min-w-0 flex-1">
              <div class="text-sm font-semibold text-gray-900 truncate">
                {{ agent.name }}
              </div>
              <div class="text-xs text-gray-500">
                {{ agent.role || '未指定' }}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-1">
            <el-tag
              size="small"
              :type="(agent.status ? statusColors[agent.status] : 'info') as any"
              class="!text-xs !px-2 !py-0 !h-5"
            >
              <el-icon v-if="agent.status && agent.status !== 'disconnected'" :size="10" class="mr-1 animate-pulse">
                <component :is="getStatusIcon(agent.status)" />
              </el-icon>
              {{ getStatusText(agent.status || 'disconnected') }}
            </el-tag>
            <el-tooltip v-if="agent.status === 'running'" content="中断此Agent" placement="top" :show-after="300">
              <el-button
                type="danger"
                size="small"
                :icon="CircleClose"
                class="!px-2 !py-1 !h-7 !w-auto min-w-[32px] border-0 bg-red-500 hover:bg-red-600 text-white shadow-sm hover:shadow transition-all duration-200 transform hover:scale-105 active:scale-95"
                title="中断此Agent"
                @click.stop="chatStore.sendAbort(agent.agent_id)"
              >
                <span class="text-xs font-medium">停止</span>
              </el-button>
            </el-tooltip>
          </div>
        </div>

        <!-- 描述 -->
        <p class="text-xs text-gray-600 mb-3 line-clamp-2 leading-relaxed">
          {{ agent.description || '暂无描述' }}
        </p>

        <!-- LLM 统计信息 -->
        <div class="bg-gradient-to-r from-gray-50 to-blue-50 rounded-lg p-2.5 border border-gray-100">
          <div class="grid grid-cols-2 gap-2 text-xs">
            <!-- 调用次数 -->
            <div class="flex items-center gap-1.5">
              <div class="p-1 bg-blue-100 rounded">
                <el-icon :size="12" class="text-blue-600">
                  <ChatDotRound />
                </el-icon>
              </div>
              <div class="flex flex-col">
                <span class="text-gray-500 text-[10px]">调用次数</span>
                <span class="font-semibold text-blue-700">{{ agent.total_llm_calls || 0 }}</span>
              </div>
            </div>

            <!-- 上下文长度 -->
            <div v-if="agent.last_context_length !== undefined" class="flex items-center gap-1.5">
              <div class="p-1 bg-purple-100 rounded">
                <el-icon :size="12" class="text-purple-600">
                  <Document />
                </el-icon>
              </div>
              <div class="flex flex-col">
                <span class="text-gray-500 text-[10px]">上下文</span>
                <span class="font-semibold text-purple-700">{{ agent.last_context_length || 0 }}</span>
              </div>
            </div>

            <!-- Token 输入 -->
            <div class="flex items-center gap-1.5">
              <div class="p-1 bg-green-100 rounded">
                <el-icon :size="12" class="text-green-600">
                  <TrendCharts />
                </el-icon>
              </div>
              <div class="flex flex-col">
                <span class="text-gray-500 text-[10px]">输入 Token</span>
                <span class="font-semibold text-green-700">{{ (agent.total_input_tokens || 0).toLocaleString() }}</span>
              </div>
            </div>

            <!-- Token 输出 -->
            <div class="flex items-center gap-1.5">
              <div class="p-1 bg-orange-100 rounded">
                <el-icon :size="12" class="text-orange-600">
                  <DataAnalysis />
                </el-icon>
              </div>
              <div class="flex flex-col">
                <span class="text-gray-500 text-[10px]">输出 Token</span>
                <span class="font-semibold text-orange-700">{{
                  (agent.total_output_tokens || 0).toLocaleString()
                }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 无Agent提示 -->
      <div v-if="agents.length === 0 && !loading" class="text-center py-8 text-gray-500">
        <el-icon :size="32" class="mb-2">
          <User />
        </el-icon>
        <p>暂无Agent</p>
        <p v-if="!chatStore.sessionId" class="text-xs mt-1">请先进入一个会话</p>
      </div>
    </div>
  </div>

  <!-- Agent配置详情弹窗 -->
  <el-dialog
    v-model="showConfigDialog"
    :title="`Agent 配置详情 - ${selectedAgent?.name || '未知'}`"
    :width="chatStore.isMobile ? '100%' : '700px'"
    :fullscreen="chatStore.isMobile"
    :close-on-click-modal="false"
    class="agent-config-dialog"
  >
    <!-- 刷新配置按钮 -->
    <div v-if="selectedAgent" class="flex items-center gap-2 mb-4">
      <el-button size="small" :icon="Refresh" :loading="configLoading" @click="refreshConfig"> 刷新配置 </el-button>
      <el-tag v-if="selectedAgentConfig" size="small" type="success"> 已加载 </el-tag>
    </div>

    <!-- 加载状态 -->
    <div v-if="configLoading" class="text-center py-8 text-gray-500">
      <el-icon :size="32" class="mb-2 animate-spin">
        <Loading />
      </el-icon>
      <p>正在获取配置信息...</p>
      <p class="text-xs mt-1">请稍候</p>
    </div>

    <!-- JSON配置信息展示 -->
    <div v-else-if="selectedAgentConfig" class="space-y-4 max-h-[60vh] overflow-y-auto">
      <!-- 配置内容（核心部分） -->
      <div v-if="selectedAgentConfig.config_content" class="bg-gray-50 p-3 rounded border">
        <div class="flex items-center gap-2 mb-2">
          <el-icon :size="16" class="text-blue-500">
            <Document />
          </el-icon>
          <span class="text-sm font-medium text-gray-700">配置内容 (config_content)</span>
        </div>
        <div class="bg-white p-3 rounded border">
          <pre class="text-sm font-mono text-gray-800 max-h-48 overflow-y-auto whitespace-pre-wrap break-all">{{
            JSON.stringify(selectedAgentConfig.config_content, null, 2)
          }}</pre>
        </div>
      </div>

      <!-- 配置内容摘要 -->
      <div v-if="selectedAgentConfig.config_content" class="bg-gray-50 p-3 rounded border">
        <div class="flex items-center gap-2 mb-2">
          <el-icon :size="16" class="text-orange-500">
            <Setting />
          </el-icon>
          <span class="text-sm font-medium text-gray-700">配置内容摘要</span>
        </div>
        <div class="space-y-2">
          <div v-if="selectedAgentConfig.config_content.name" class="flex justify-between items-center text-sm">
            <span class="text-gray-600">配置名称:</span>
            <span class="font-medium text-gray-800">{{ selectedAgentConfig.config_content.name }}</span>
          </div>
          <div v-if="selectedAgentConfig.config_content.role" class="flex justify-between items-center text-sm">
            <span class="text-gray-600">角色:</span>
            <span class="font-medium text-gray-800">{{ selectedAgentConfig.config_content.role }}</span>
          </div>
          <div
            v-if="selectedAgentConfig.config_content.llm_config_name"
            class="flex justify-between items-center text-sm"
          >
            <span class="text-gray-600">LLM配置:</span>
            <span class="font-medium text-gray-800">{{ selectedAgentConfig.config_content.llm_config_name }}</span>
          </div>
          <div
            v-if="selectedAgentConfig.config_content.tools && selectedAgentConfig.config_content.tools.length > 0"
            class="flex justify-between items-center text-sm"
          >
            <span class="text-gray-600">工具数量:</span>
            <span class="font-medium text-gray-800">{{ selectedAgentConfig.config_content.tools.length }}</span>
          </div>
          <div v-if="selectedAgentConfig.config_content.workspace" class="flex justify-between items-center text-sm">
            <span class="text-gray-600">工作空间:</span>
            <span class="font-medium text-gray-800 truncate">{{ selectedAgentConfig.config_content.workspace }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 无配置信息提示 -->
    <div v-else class="text-center py-8 text-gray-500">
      <el-icon :size="32" class="mb-2">
        <Setting />
      </el-icon>
      <p>暂无配置信息</p>
      <p class="text-xs mt-1">请选择一个Agent查看配置</p>
    </div>

    <!-- 弹窗底部按钮 -->
    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button size="small" @click="closeConfigDialog"> 关闭 </el-button>
        <el-button type="primary" size="small" @click="sendMessageToAgent"> 发送消息给此Agent </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.overflow-y-auto::-webkit-scrollbar {
  width: 6px;
}

.overflow-y-auto::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.overflow-y-auto::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

:deep(.agent-config-dialog) {
  max-height: 80vh;
}

:deep(.agent-config-dialog .el-dialog__body) {
  padding: 20px;
}

/* 移动端优化 */
@media (max-width: 768px) {
  :deep(.agent-config-dialog) {
    margin: 0 !important;
    border-radius: 0 !important;
    width: 100% !important;
    max-height: 100vh;
    overflow: hidden;
  }

  :deep(.agent-config-dialog .el-dialog__header) {
    padding: 16px 20px;
    margin: 0;
    border-bottom: 1px solid var(--el-border-color-light);
  }

  :deep(.agent-config-dialog .el-dialog__title) {
    font-size: 18px;
    font-weight: 600;
  }

  :deep(.agent-config-dialog .el-dialog__body) {
    padding: 16px 20px !important;
    overflow-y: auto;
    flex: 1;
    max-height: calc(100vh - 120px);
  }

  :deep(.agent-config-dialog .el-dialog__footer) {
    padding: 12px 20px;
    border-top: 1px solid var(--el-border-color-light);
  }

  :deep(.agent-config-dialog pre) {
    font-size: 12px;
    line-height: 1.4;
  }
}
</style>
