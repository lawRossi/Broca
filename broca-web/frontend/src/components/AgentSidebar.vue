<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch, computed } from 'vue'
import { useChatStore, useAgentStore } from '@/stores'
import type { Agent } from '@/stores/agent'
import { ElIcon, ElTooltip, ElTag, ElButton, ElDialog, ElSelect, ElOption, ElMessage, ElInput, ElCheckbox, ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus'
import {
  UserFilled,
  QuestionFilled,
  Tools,
  Document,
  Upload,
  Download,
  Connection,
  ChatDotRound,
  Setting,
} from '@element-plus/icons-vue'

const chatStore = useChatStore()
const agentStore = useAgentStore()

const showConfigDialog = ref(false)
const loading = ref(false)
const selectedAgent = ref<Agent | null>(null)
const autoRefreshInterval = ref<number | null>(null)
const lastRefreshTime = ref<Date>(new Date())

// LLM 配置编辑相关
const editableConfigContent = ref<string>('')
const selectedProvider = ref<string>('')
const selectedModel = ref<string>('')
const availableProviders = ref<{ id: string; name: string }[]>([])
const availableModels = ref<{ id: string; name: string }[]>([])
const saving = ref(false)

// 使用 computed 从 agentStore 获取 agents 列表
const agents = computed(() => agentStore.agents)

// 使用 computed 从 agentStore 获取选中的 agent 配置
const selectedAgentConfig = computed(() => agentStore.selectedAgentConfig)
const configLoading = computed(() => agentStore.loading)

// Agent 消息过滤相关
const allVisible = computed(() => {
  return agents.value.length > 0 && agents.value.every((a) => agentStore.visibleAgentIds.includes(a.agent_id))
})

const handleFilterCommand = (command: string) => {
  if (command === 'selectAll') {
    toggleAll()
  }
}

const toggleAll = () => {
  if (allVisible.value) {
    agentStore.setVisibleAgents([])
  } else {
    agentStore.setVisibleAgents(agents.value.map((a) => a.agent_id))
  }
}

const statusColors: Record<string, string> = {
  idle: 'success',
  running: 'primary',
  connecting: 'warning',
  disconnected: 'danger',
}

const typeIcons: Record<string, any> = {
  assistant: UserFilled,
  code_assistant: Document
}

const typeColors: Record<string, string> = {
  assistant: 'blue',
  code_assistant: 'green',
  research_assistant: 'orange',
  task_manager: 'purple',
  data_analyst: 'cyan',
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

// 刷新配置
const refreshConfig = async () => {
  if (!selectedAgent.value || !chatStore.sessionId) return
  const config = await agentStore.fetchAgentConfig(chatStore.sessionId, selectedAgent.value.agent_id)
  if (config) {
    agentStore.selectedAgentConfig = config
  }
  initConfigEdit()
}

// 初始化配置编辑状态
const initConfigEdit = async () => {
  if (!selectedAgentConfig.value?.config_content) return

  // 设置可编辑的配置内容
  editableConfigContent.value = JSON.stringify(selectedAgentConfig.value.config_content, null, 2)

  // 加载 LLM 提供商列表
  await agentStore.fetchLLMProviders()
  availableProviders.value = agentStore.llmProviders

  // 从当前配置中提取 provider 和 model
  const config = selectedAgentConfig.value.config_content
  selectedProvider.value = config.provider || ''
  selectedModel.value = config.model || ''

  // 如果已有 provider，加载对应的 models
  if (selectedProvider.value) {
    await agentStore.fetchLLMModels(selectedProvider.value)
    availableModels.value = agentStore.llmModels
  }
}

// 当提供商改变时，更新模型列表
const handleProviderChange = async (provider: string) => {
  selectedProvider.value = provider
  selectedModel.value = ''
  if (provider) {
    await agentStore.fetchLLMModels(provider)
    availableModels.value = agentStore.llmModels
  } else {
    availableModels.value = []
  }
}

// 保存配置
const saveConfig = async () => {
  if (!selectedAgent.value || !chatStore.sessionId || !selectedAgentConfig.value) return

  saving.value = true
  try {
    // 解析当前编辑的配置内容
    let configContent: Record<string, any>
    try {
      configContent = JSON.parse(editableConfigContent.value)
    } catch (e) {
      ElMessage.error('配置内容 JSON 格式有误，请检查后重试')
      return
    }

    // 更新 provider 和 model
    if (selectedProvider.value) {
      configContent.provider = selectedProvider.value
    }
    if (selectedModel.value) {
      configContent.model = selectedModel.value
    }

    // 保存到后端
    const success = await agentStore.saveAgentConfig(
      chatStore.sessionId,
      selectedAgent.value.agent_id,
      configContent,
    )

    if (success) {
      ElMessage.success({
        message: '配置保存成功！请重启 session 进程以使更改生效。',
        duration: 6000,
      })
      // 刷新配置信息，显示更新后的值
      await refreshConfig()
    }
  } finally {
    saving.value = false
  }
}

// 点击查看 Agent 配置
const handleAgentClick = async (agent: Agent) => {
  // 打开配置弹窗时暂停自动刷新，避免覆盖用户编辑
  stopAutoRefresh()
  selectedAgent.value = agent
  // 使用 agentStore 的 selectAgent 方法来获取配置
  if (chatStore.sessionId) {
    await agentStore.selectAgent(agent.agent_id, chatStore.sessionId)
    await initConfigEdit()
  }
  showConfigDialog.value = true
}

// 关闭配置弹窗
const closeConfigDialog = () => {
  showConfigDialog.value = false
  selectedAgent.value = null
  agentStore.selectedAgentConfig = null
  editableConfigContent.value = ''
  selectedProvider.value = ''
  selectedModel.value = ''
  // 关闭弹窗后，仅在 runner 运行时恢复自动刷新
  if (chatStore.sessionId && chatStore.runnerAlive) {
    startAutoRefresh(10000)
  }
}

// 监听 Runner 状态变化，控制自动刷新启停
watch(
  () => chatStore.runnerAlive,
  (isAlive) => {
    if (isAlive && chatStore.sessionId) {
      startAutoRefresh(10000)
    } else {
      stopAutoRefresh()
    }
  },
  { immediate: true }
)

// 监听 session 变化，当 runner 运行时自动刷新 agents
watch(
  () => chatStore.sessionId,
  (newSessionId, oldSessionId) => {
    if (newSessionId && newSessionId !== oldSessionId && chatStore.runnerAlive) {
      startAutoRefresh(10000)
    } else if (!newSessionId) {
      stopAutoRefresh()
    }
  }
)

onMounted(() => {
  if (chatStore.sessionId && chatStore.runnerAlive) {
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
    class="col-span-10 lg:col-span-2 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      flex: !chatStore.isMobile || chatStore.showLeftSidebar,
      hidden: chatStore.isMobile && !chatStore.showLeftSidebar,
      'fixed inset-x-0 top-[57px] bottom-0 z-40 bg-gray-50 p-3 rounded-none border-t lg:rounded-lg shadow-xl border':
        chatStore.isMobile && chatStore.showLeftSidebar,
    }"
  >
    <!-- Agent面板标题 -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-gray-900">Session Agents</h3>
      </div>
      <div class="flex items-center gap-1">
        <!-- Agent 消息过滤下拉 -->
        <el-dropdown trigger="click" @command="handleFilterCommand">
          <el-button size="small" class="!p-1 !h-6 !w-6" :disabled="!agents.length">
            <el-icon :size="14"><Setting /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="selectAll">
                <el-checkbox :model-value="allVisible" size="small" @click.stop="toggleAll" />
                <span class="ml-1">全部</span>
              </el-dropdown-item>
              <el-dropdown-item
                v-for="agent in agents"
                :key="agent.agent_id"
                :command="agent.agent_id"
              >
                <el-checkbox
                  :model-value="agentStore.visibleAgentIds.includes(agent.agent_id)"
                  size="small"
                  @click.stop="agentStore.toggleAgentVisibility(agent.agent_id)"
                />
                <span class="ml-1 truncate" :title="agent.name">{{ agent.name }}</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- Agent列表 -->
    <div class="space-y-3">
      <div
        v-for="agent in agents"
        :key="agent.agent_id"
        class="bg-white rounded-lg border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 cursor-pointer"
        :class="{
          'ring-2 ring-blue-500': agentStore.currentAgentId === agent.agent_id,
        }"
        @click="handleAgentClick(agent)"
      >
        <!-- Agent 头部：名称、类型、状态 -->
        <div class="flex items-start justify-between mb-3">
          <div class="flex items-center gap-2 min-w-0 flex-1">
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
              {{ getStatusText(agent.status || 'disconnected') }}
            </el-tag>
            <el-tooltip v-if="agent.status === 'running'" content="中断此Agent" placement="top" :show-after="300">
              <el-button
                type="danger"
                size="small"
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
        <p v-if="agent.description" class="text-xs text-gray-600 mb-3 line-clamp-2 leading-relaxed">
          {{ agent.description }}
        </p>

        <!-- LLM 统计信息 -->
        <div class="bg-gradient-to-r from-gray-50 to-blue-50 rounded-lg p-2.5 border border-gray-100">
          <div class="grid grid-cols-2 gap-2 text-xs stats-grid">
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
                  <Download />
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
                  <Upload />
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
      <!-- LLM 提供商和模型选择 -->
      <div v-if="selectedAgentConfig.config_content" class="bg-gray-50 p-3 rounded border">
        <div class="flex items-center gap-2 mb-3">
          <el-icon :size="16" class="text-purple-500">
            <Setting />
          </el-icon>
          <span class="text-sm font-medium text-gray-700">LLM 配置</span>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs text-gray-600 mb-1">Provider</label>
            <el-select
              v-model="selectedProvider"
              placeholder="选择 LLM 提供商"
              size="small"
              style="width: 100%"
              @change="handleProviderChange"
            >
              <el-option
                v-for="p in availableProviders"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
            </el-select>
          </div>
          <div>
            <label class="block text-xs text-gray-600 mb-1">Model</label>
            <el-select
              v-model="selectedModel"
              placeholder="选择模型"
              size="small"
              style="width: 100%"
              :disabled="!selectedProvider"
            >
              <el-option
                v-for="m in availableModels"
                :key="m.id"
                :label="m.name"
                :value="m.id"
              />
            </el-select>
          </div>
        </div>
      </div>

      <!-- 配置内容（可编辑） -->
      <div v-if="selectedAgentConfig.config_content" class="bg-gray-50 p-3 rounded border">
        <div class="flex items-center gap-2 mb-2">
          <el-icon :size="16" class="text-blue-500">
            <Document />
          </el-icon>
          <span class="text-sm font-medium text-gray-700">配置内容 (config_content) <span class="text-xs text-gray-400 font-normal">- 可编辑 JSON</span></span>
        </div>
        <el-input
          v-model="editableConfigContent"
          type="textarea"
          :rows="12"
          class="config-editor"
          placeholder="在此编辑配置 JSON..."
        />
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
        <el-button
          type="primary"
          size="small"
          :loading="saving"
          :disabled="!selectedAgentConfig"
          @click="saveConfig"
        >
          保存
        </el-button>
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
  width: 4px;
}

.stats-grid {
  grid-template-columns: 1fr 1fr !important;
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

/* 配置编辑器样式 */
.config-editor :deep(.el-textarea__inner) {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  min-height: 200px;
  background-color: #1e1e2e;
  color: #cdd6f4;
  border: 1px solid #45475a;
  border-radius: 6px;
  padding: 12px;
  tab-size: 2;
}

.config-editor :deep(.el-textarea__inner:focus) {
  border-color: #89b4fa;
  box-shadow: 0 0 0 1px #89b4fa;
}

/* 下拉选择框样式 */
:deep(.el-select) {
  --el-select-border-color-hover: #89b4fa;
  --el-select-input-focus-border-color: #89b4fa;
}
</style>
