<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage, onMessage } from '../api/vscode'

const chatStore = useChatStore()

// ==================== 状态图标映射 ====================
const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  idle: { color: 'var(--success-fg)', bg: 'rgba(34,197,94,0.12)', label: '空闲' },
  running: { color: 'var(--focus-border)', bg: 'rgba(59,130,246,0.12)', label: '运行中' },
  connecting: { color: 'var(--warning-fg)', bg: 'rgba(234,179,8,0.12)', label: '连接中' },
  disconnected: { color: 'var(--text-secondary)', bg: 'rgba(156,163,175,0.12)', label: '断开' },
}

// ==================== 类型图标 ====================
const typeIcons: Record<string, string> = {
  assistant: '🤖',
  code_assistant: '💻',
  research_assistant: '🔍',
  task_manager: '📋',
  data_analyst: '📊',
}

function getTypeIcon(type: string | undefined): string {
  return typeIcons[type || 'assistant'] || '🤖'
}

const typeColors: Record<string, string> = {
  assistant: 'var(--text-link)',
  code_assistant: 'var(--success-fg)',
  research_assistant: 'var(--warning-fg)',
  task_manager: '#a855f7',
  data_analyst: '#06b6d4',
}

function getTypeColor(type: string | undefined): string {
  return typeColors[type || 'assistant'] || 'var(--text-link)'
}

// ==================== Agent 运行时状态 ====================
function getStatus(agentId: string | undefined): string {
  if (!agentId) return 'disconnected'
  return chatStore.agentStatuses[agentId] || 'disconnected'
}

function handleAbort(agentId: string) {
  chatStore.sendAbort(agentId)
}

// ==================== 选中的 Agent 配置弹窗 ====================
const showConfigDialog = ref(false)
const selectedAgent = ref<any>(null)

// Agent 配置数据
const agentConfig = ref<any>(null)
const configLoading = ref(false)

// LLM 配置编辑相关
const selectedProvider = ref<string>('')
const selectedModel = ref<string>('')
const availableProviders = ref<{ id: string; name: string }[]>([])
const availableModels = ref<{ id: string; name: string }[]>([])
const saving = ref(false)

// ==================== Agent 配置表单模型（分组表单编辑） ====================
const configForm = ref<any>({
  name: '',
  role: '',
  server_url: '',
  tools: [] as string[],
  skills: '',
  mcp_servers: '',
  interactive: true,
  save_history: true,
  track_session_momory: false,
  enable_context_compression: false,
  workspace: '',
  environment: '',
  system_prompt_template: '',
  session_memory_config: {
    minimum_messages_to_init: 200,
    minimum_messages_between_update: 100,
    steps_between_updates: 50,
  },
  persistent_memory_config: {
    auto_extract: false,
    minimum_messages_to_init: 50,
    minimum_messages_between_update: 30,
    steps_between_updates: 20,
    freshness_warning_days: 7,
  },
  compact_config: {
    session_trunc_threshold: 250000,
    session_trunc_percentage: 0.5,
  },
})

// 可选工具列表（用于 tools 多选，允许用户自定义输入）
const availableTools = ref<string[]>([
  'read_file',
  'write_file',
  'edit_file',
  'glob',
  'grep',
  'list_dir',
  'tree_dir',
  'web_fetch',
  'web_search',
  'ask_user',
  'assign_task',
  'bash',
  'cron',
  'task_management',
  'todo_management',
  'load_skill',
  'skill_manage',
  'memory',
  'read_blackboard',
  'write_blackboard',
  'list_blackboard',
  'delete_blackboard',
  'blackboard_changes',
])

function resetConfigForm() {
  configForm.value = {
    name: '',
    role: '',
    server_url: '',
    tools: [],
    skills: '',
    mcp_servers: '',
    interactive: true,
    save_history: true,
    track_session_momory: false,
    enable_context_compression: false,
    workspace: '',
    environment: '',
    system_prompt_template: '',
    session_memory_config: {},
    persistent_memory_config: {},
    compact_config: {},
  }
}

// ==================== 工具多选下拉 ====================
const showToolsMenu = ref(false)
const toolsSearch = ref('')

const filteredTools = computed(() => {
  const q = toolsSearch.value.trim().toLowerCase()
  if (!q) return availableTools.value
  return availableTools.value.filter((t) => t.toLowerCase().includes(q))
})

function hasTool(tool: string): boolean {
  return configForm.value.tools?.includes(tool) ?? false
}

function toggleTool(tool: string) {
  const idx = configForm.value.tools.indexOf(tool)
  if (idx === -1) {
    configForm.value.tools.push(tool)
  } else {
    configForm.value.tools.splice(idx, 1)
  }
}

function removeTool(tool: string) {
  toggleTool(tool)
}

function addCustomTool() {
  const name = toolsSearch.value.trim()
  if (!name) return
  if (!configForm.value.tools.includes(name)) {
    configForm.value.tools.push(name)
  }
  if (!availableTools.value.includes(name)) {
    availableTools.value.push(name)
  }
  toolsSearch.value = ''
}

function handleAgentClick(agent: any) {
  // 打开配置弹窗时暂停自动刷新，避免覆盖用户编辑
  stopAutoRefresh()
  selectedAgent.value = agent
  showConfigDialog.value = true
  configLoading.value = true
  agentConfig.value = null

  // 请求获取 Agent 配置
  postMessage({
    type: 'fetchAgentConfig',
    payload: { agentId: agent.agent_id },
  })
}

// ==================== Agent 消息可见性过滤 ====================
const showFilterDropdown = ref(false)

const allVisible = computed(() => {
  return chatStore.agents.length > 0 && chatStore.agents.every((a) => chatStore.visibleAgentIds.includes(a.agent_id))
})

function toggleAll() {
  if (allVisible.value) {
    chatStore.setVisibleAgents([])
  } else {
    chatStore.setVisibleAgents(chatStore.agents.map((a) => a.agent_id))
  }
}

function closeConfigDialog() {
  showConfigDialog.value = false
  selectedAgent.value = null
  agentConfig.value = null
  resetConfigForm()
  selectedProvider.value = ''
  selectedModel.value = ''
  // 关闭弹窗后，仅在 runner 运行时恢复自动刷新
  if (chatStore.sessionId && chatStore.runnerAlive) {
    startAutoRefresh(10000)
  }
}

function refreshConfig() {
  if (!selectedAgent.value) return
  configLoading.value = true
  postMessage({
    type: 'fetchAgentConfig',
    payload: { agentId: selectedAgent.value.agent_id },
  })
}

function fetchLLMProviders() {
  postMessage({ type: 'fetchLLMProviders' })
}

function fetchLLMModels(provider: string) {
  postMessage({ type: 'fetchLLMModels', payload: { provider } })
}

function initConfigEdit() {
  if (!agentConfig.value?.config_content) return

  const config = agentConfig.value.config_content
  selectedProvider.value = config.provider || ''
  selectedModel.value = config.model || ''

  // 填充表单字段
  configForm.value = {
    name: config.name ?? '',
    role: config.role ?? '',
    server_url: config.server_url ?? '',
    tools: Array.isArray(config.tools)
      ? [...config.tools]
      : config.tools
        ? String(config.tools)
            .split(',')
            .map((s: string) => s.trim())
            .filter(Boolean)
        : [],
    skills: config.skills ?? '',
    mcp_servers:
      config.mcp_servers !== undefined && config.mcp_servers !== null
        ? JSON.stringify(config.mcp_servers, null, 2)
        : '',
    interactive: config.interactive ?? true,
    save_history: config.save_history ?? true,
    track_session_momory: config.track_session_momory ?? false,
    enable_context_compression: config.enable_context_compression ?? false,
    workspace: config.workspace ?? '',
    environment: config.environment ?? '',
    system_prompt_template: config.system_prompt_template ?? '',
    session_memory_config: { ...(config.session_memory_config || {}) },
    persistent_memory_config: { ...(config.persistent_memory_config || {}) },
    compact_config: { ...(config.compact_config || {}) },
  }

  fetchLLMProviders()

  if (selectedProvider.value) {
    fetchLLMModels(selectedProvider.value)
  }
}

function handleProviderChange(provider: string) {
  selectedProvider.value = provider
  selectedModel.value = ''
  if (provider) {
    fetchLLMModels(provider)
  } else {
    availableModels.value = []
  }
}

// 由表单字段构造 config_content 对象
function buildConfigContent(): Record<string, any> {
  const form = configForm.value
  const original = { ...(agentConfig.value?.config_content || {}) }

  let mcpServers: any = undefined
  const mcpStr = (form.mcp_servers || '').trim()
  if (mcpStr) {
    try {
      mcpServers = JSON.parse(mcpStr)
    } catch {
      mcpServers = original.mcp_servers
    }
  }

  const configContent: Record<string, any> = {
    ...original,
    name: form.name,
    role: form.role,
    server_url: form.server_url,
    tools: form.tools,
    skills: form.skills,
    interactive: form.interactive,
    save_history: form.save_history,
    track_session_momory: form.track_session_momory,
    enable_context_compression: form.enable_context_compression,
    workspace: form.workspace,
    environment: form.environment,
    system_prompt_template: form.system_prompt_template,
    session_memory_config: { ...form.session_memory_config },
    persistent_memory_config: { ...form.persistent_memory_config },
    compact_config: { ...form.compact_config },
  }
  if (mcpServers !== undefined) {
    configContent.mcp_servers = mcpServers
  } else {
    delete configContent.mcp_servers
  }

  if (selectedProvider.value) configContent.provider = selectedProvider.value
  if (selectedModel.value) configContent.model = selectedModel.value

  return configContent
}

function saveConfig() {
  if (!selectedAgent.value || !agentConfig.value) return

  saving.value = true
  // 兜底：若长时间未收到 extension 响应，恢复按钮状态，避免卡在“保存中...”
  window.setTimeout(() => {
    saving.value = false
  }, 15000)
  try {
    const configContent = buildConfigContent()

    // 深度序列化为纯 JSON，避免 payload 内含 Vue 响应式 Proxy 导致 postMessage 序列化抛错
    const plainConfig = JSON.parse(JSON.stringify(configContent))

    postMessage({
      type: 'updateAgentConfig',
      payload: {
        agentId: selectedAgent.value.agent_id,
        config_content: plainConfig,
      },
    })
  } catch (e: any) {
    // 发送失败：立即恢复按钮状态并给出真实错误信息，便于定位
    const errMsg = typeof e?.message === 'string' ? e.message : String(e)
    console.error('[AgentSidebar] Failed to post updateAgentConfig message:', e)
    saving.value = false
    chatStore.showError(`保存失败：${errMsg || '无法发送保存请求'}`, 'error', 6000)
  }
}

// ==================== 监听来自 Extension 的消息 ====================
const unsubMessage = ref<(() => void) | null>(null)

function handleDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.filter-dropdown')) {
    showFilterDropdown.value = false
  }
  if (!target.closest('.tools-select')) {
    showToolsMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  unsubMessage.value = onMessage((data: any) => {
    switch (data.type) {
      case 'agentConfig':
        agentConfig.value = data.payload
        configLoading.value = false
        // 等待下一个 tick 确保 DOM 更新后再初始化编辑
        setTimeout(() => initConfigEdit(), 0)
        break

      case 'agentConfigSaved':
        agentConfig.value = data.payload
        configLoading.value = false
        saving.value = false
        chatStore.showError('配置保存成功！请重启 session 进程以使更改生效。', 'info', 6000)
        // 刷新配置信息，显示更新后的值
        setTimeout(() => initConfigEdit(), 0)
        break

      case 'providers':
        availableProviders.value = data.payload || []
        break

      case 'models':
        availableModels.value = data.payload || []
        break

      case 'error':
        configLoading.value = false
        saving.value = false
        chatStore.showError(data.payload?.message || '操作失败', 'error', 6000)
        break
    }
  })

  if (chatStore.sessionId && chatStore.runnerAlive) startAutoRefresh(10000)
})

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

// 额外监听 runner status 变化作为后备：当 status 变为 'alive' 时确保自动轮询启动
// 与 runnerAlive watcher 互补，处理 computed 可能因竞态未触发的边界情况
watch(
  () => chatStore.runnerInfo?.status,
  (newStatus) => {
    if (newStatus === 'alive' && chatStore.sessionId) {
      if (!autoRefreshInterval.value) {
        refreshAgents()
        startAutoRefresh(10000)
      }
    }
  }
)

onUnmounted(() => {
  stopAutoRefresh()
  document.removeEventListener('click', handleDocumentClick)
  if (unsubMessage.value) {
    unsubMessage.value()
  }
})

// ==================== 自动刷新 ====================
const autoRefreshInterval = ref<number | null>(null)
const loading = ref(false)

function refreshAgents() {
  loading.value = true
  postMessage({
    type: 'fetchAgents',
    payload: { sessionId: chatStore.sessionId },
  })
  loading.value = false
}

function startAutoRefresh(intervalMs: number = 10000) {
  if (autoRefreshInterval.value) stopAutoRefresh()
  autoRefreshInterval.value = window.setInterval(() => {
    if (chatStore.sessionId && !loading.value) {
      refreshAgents()
    }
  }, intervalMs)
}

function stopAutoRefresh() {
  if (autoRefreshInterval.value) {
    clearInterval(autoRefreshInterval.value)
    autoRefreshInterval.value = null
  }
}

watch(
  () => chatStore.sessionId,
  (newId) => {
    if (newId && chatStore.runnerAlive) startAutoRefresh(10000)
    else stopAutoRefresh()
  }
)

// ==================== Agent 列表（main_agent 排第一） ====================
const sortedAgents = computed(() => {
  const agents = [...chatStore.agents]
  const mainId = chatStore.defaultAgentId
  if (!mainId) return agents
  const mainIdx = agents.findIndex((a) => a.agent_id === mainId)
  if (mainIdx > 0) {
    const [main] = agents.splice(mainIdx, 1)
    agents.unshift(main)
  }
  return agents
})
const isOpen = computed(() => chatStore.showLeftSidebar)
</script>

<template>
  <div class="agent-sidebar" :class="{ open: isOpen }">
    <!-- 标题栏 -->
    <div class="sidebar-header">
      <div class="header-title">
        <span>🤖 Agents</span>
      </div>
      <div class="header-actions">
        <!-- Agent 消息过滤 -->
        <div v-if="sortedAgents.length > 0" class="filter-dropdown">
          <button class="icon-btn filter-btn" title="过滤Agent消息" @click="showFilterDropdown = !showFilterDropdown">
            ⚙️
          </button>
          <div v-if="showFilterDropdown" class="filter-menu" @click.stop>
            <label class="filter-item" @click="toggleAll">
              <input type="checkbox" :checked="allVisible" />
              <span>全部</span>
            </label>
            <label
              v-for="agent in chatStore.agents"
              :key="agent.agent_id"
              class="filter-item"
              @click="chatStore.toggleAgentVisibility(agent.agent_id)"
            >
              <input type="checkbox" :checked="chatStore.visibleAgentIds.includes(agent.agent_id)" />
              <span class="truncate" :title="agent.name">{{ agent.name }}</span>
            </label>
          </div>
        </div>
        <button class="close-btn" @click="chatStore.toggleLeftSidebar()">✕</button>
      </div>
    </div>

    <!-- Agent 列表 -->
    <div class="agent-list">
      <div v-if="sortedAgents.length === 0" class="empty-agents">No agents available</div>
      <div
        v-for="agent in sortedAgents"
        :key="agent.agent_id"
        class="agent-card"
        :class="{ 'card-main': agent.agent_id === chatStore.defaultAgentId }"
        @click="handleAgentClick(agent)"
      >
        <!-- Agent 头部 -->
        <div class="card-header">
          <div class="agent-info">
            <div class="agent-name-group">
              <span class="agent-name">{{ agent.name }}</span>
              <span class="agent-role">{{ agent.role || '未指定' }}</span>
            </div>
          </div>
          <div class="agent-actions">
            <span
              class="status-tag"
              :style="{
                color: statusConfig[getStatus(agent.agent_id)]?.color,
                background: statusConfig[getStatus(agent.agent_id)]?.bg,
              }"
            >
              <span class="status-dot" :class="{ 'dot-pulse': getStatus(agent.agent_id) === 'running' }"></span>
              {{ statusConfig[getStatus(agent.agent_id)]?.label || '断开' }}
            </span>
            <button
              v-if="getStatus(agent.agent_id) === 'running'"
              class="abort-btn"
              title="中断此 Agent"
              @click.stop="handleAbort(agent.agent_id)"
            >
              ⏹
            </button>
          </div>
        </div>

        <!-- 描述 -->
        <p v-if="agent.description" class="agent-desc">{{ agent.description }}</p>

        <!-- LLM 统计信息 -->
        <div class="stats-section">
          <div class="stat-item">
            <span class="stat-icon" style="background: rgba(59, 130, 246, 0.12)">💬</span>
            <div class="stat-text">
              <span class="stat-label">调用次数</span>
              <span class="stat-value" style="color: var(--text-link)">{{ agent.total_llm_calls || 0 }}</span>
            </div>
          </div>
          <div v-if="agent.last_context_length !== undefined" class="stat-item">
            <span class="stat-icon" style="background: rgba(168, 85, 247, 0.12)">📄</span>
            <div class="stat-text">
              <span class="stat-label">上下文</span>
              <span class="stat-value" style="color: #a855f7">{{ agent.last_context_length || 0 }}</span>
            </div>
          </div>
          <div class="stat-item">
            <span class="stat-icon" style="background: rgba(34, 197, 94, 0.12)">⬇️</span>
            <div class="stat-text">
              <span class="stat-label">输入 Token</span>
              <span class="stat-value" style="color: var(--success-fg)">{{
                (agent.total_input_tokens || 0).toLocaleString()
              }}</span>
            </div>
          </div>
          <div class="stat-item">
            <span class="stat-icon" style="background: rgba(234, 179, 8, 0.12)">⬆️</span>
            <div class="stat-text">
              <span class="stat-label">输出 Token</span>
              <span class="stat-value" style="color: var(--warning-fg)">{{
                (agent.total_output_tokens || 0).toLocaleString()
              }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== Agent 配置详情弹窗 ==================== -->
    <Teleport to="body">
      <div v-if="showConfigDialog" class="dialog-overlay" @click.self="closeConfigDialog">
        <div class="config-dialog">
          <div class="dialog-header">
            <span class="dialog-title">Agent 配置详情 - {{ selectedAgent?.name || '未知' }}</span>
            <button class="close-btn" @click="closeConfigDialog">✕</button>
          </div>
          <div class="dialog-body">
            <!-- 刷新配置按钮 -->
            <div class="config-toolbar">
              <button class="btn btn-secondary btn-small" :disabled="configLoading" @click="refreshConfig">
                🔄 刷新配置
              </button>
              <span v-if="agentConfig" class="loaded-badge">已加载</span>
            </div>

            <!-- 加载状态 -->
            <div v-if="configLoading" class="loading-state">
              <p>正在获取配置信息...</p>
              <p class="hint">请稍候</p>
            </div>

            <!-- 配置内容 -->
            <div v-else-if="agentConfig" class="config-edit-area">
              <!-- LLM 提供商和模型选择 -->
              <div class="section-box">
                <div class="section-title">
                  <span>⚙️ LLM 配置</span>
                </div>
                <div class="llm-grid">
                  <div class="field">
                    <label>Provider</label>
                    <select v-model="selectedProvider" @change="handleProviderChange(selectedProvider)">
                      <option value="" disabled>选择 LLM 提供商</option>
                      <option v-for="p in availableProviders" :key="p.id" :value="p.id">{{ p.name }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Model</label>
                    <select v-model="selectedModel" :disabled="!selectedProvider">
                      <option value="" disabled>选择模型</option>
                      <option v-for="m in availableModels" :key="m.id" :value="m.id">{{ m.name }}</option>
                    </select>
                  </div>
                </div>
              </div>

              <!-- 基本信息 -->
              <div class="section-box">
                <div class="section-title">
                  <span>👤 基本信息</span>
                </div>
                <div class="form-grid">
                  <div class="field">
                    <label>Name</label>
                    <input v-model="configForm.name" placeholder="Agent 名称" />
                  </div>
                  <div class="field">
                    <label>Role</label>
                    <input v-model="configForm.role" placeholder="角色标识" />
                  </div>
                </div>
              </div>

              <!-- 工具与技能 -->
              <div class="section-box">
                <div class="section-title">
                  <span>🛠️ 工具与技能</span>
                </div>
                <div class="form-grid">
                  <div class="field full">
                    <label>Tools</label>
                    <div class="tools-select" @click.stop>
                      <div class="tools-trigger" @click="showToolsMenu = !showToolsMenu">
                        <div class="tools-tags">
                          <span v-for="t in configForm.tools" :key="t" class="tool-tag">
                            {{ t }}
                            <span class="tool-tag-remove" @click.stop="removeTool(t)">×</span>
                          </span>
                          <span v-if="!configForm.tools.length" class="tools-placeholder">选择或输入工具名称</span>
                        </div>
                        <span class="tools-caret">▾</span>
                      </div>
                      <div v-if="showToolsMenu" class="tools-menu">
                        <div class="tools-search-row">
                          <input
                            v-model="toolsSearch"
                            class="tools-search"
                            placeholder="搜索或输入新增..."
                            @keydown.enter.prevent="addCustomTool"
                          />
                        </div>
                        <div
                          v-if="toolsSearch.trim() && !availableTools.includes(toolsSearch.trim())"
                          class="tools-add"
                        >
                          <button class="tools-add-btn" @click="addCustomTool">新增 "{{ toolsSearch.trim() }}"</button>
                        </div>
                        <div class="tools-list">
                          <label v-for="t in filteredTools" :key="t" class="tools-option" @click.stop="toggleTool(t)">
                            <input type="checkbox" :checked="hasTool(t)" />
                            <span>{{ t }}</span>
                          </label>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="field">
                    <label>Skills</label>
                    <input v-model="configForm.skills" placeholder="如 all 或以逗号分隔" />
                  </div>
                  <div class="field full">
                    <label>MCP Servers（JSON）</label>
                    <textarea v-model="configForm.mcp_servers" rows="3" placeholder="[]" spellcheck="false"></textarea>
                  </div>
                </div>
              </div>

              <!-- 行为开关 -->
              <div class="section-box">
                <div class="section-title">
                  <span>⚙️ 行为开关</span>
                </div>
                <div class="switch-list">
                  <label class="switch-item">
                    <span>Interactive</span>
                    <input type="checkbox" v-model="configForm.interactive" />
                  </label>
                  <label class="switch-item">
                    <span>Save History</span>
                    <input type="checkbox" v-model="configForm.save_history" />
                  </label>
                  <label class="switch-item">
                    <span>Track Session Memory</span>
                    <input type="checkbox" v-model="configForm.track_session_momory" />
                  </label>
                  <label class="switch-item">
                    <span>启用上下文压缩</span>
                    <input type="checkbox" v-model="configForm.enable_context_compression" />
                  </label>
                </div>
              </div>

              <!-- 运行环境 -->
              <div class="section-box">
                <div class="section-title">
                  <span>🌐 运行环境</span>
                </div>
                <div class="form-grid">
                  <div class="field full">
                    <label>Workspace</label>
                    <input v-model="configForm.workspace" placeholder="工作空间路径" />
                  </div>
                  <div class="field full">
                    <label>System Prompt Template</label>
                    <textarea v-model="configForm.system_prompt_template" rows="6"></textarea>
                  </div>
                  <div class="field full">
                    <label>Environment</label>
                    <textarea v-model="configForm.environment" rows="3"></textarea>
                  </div>
                </div>
              </div>

              <!-- Session Memory 配置 -->
              <div class="section-box">
                <div class="section-title">
                  <span>💬 Session Memory 配置</span>
                </div>
                <div class="form-grid">
                  <div class="field">
                    <label>最小消息数(初始化)</label>
                    <input
                      type="number"
                      v-model.number="configForm.session_memory_config.minimum_messages_to_init"
                      min="0"
                    />
                  </div>
                  <div class="field">
                    <label>更新间隔消息数</label>
                    <input
                      type="number"
                      v-model.number="configForm.session_memory_config.minimum_messages_between_update"
                      min="0"
                    />
                  </div>
                  <div class="field">
                    <label>更新 Step 数</label>
                    <input
                      type="number"
                      v-model.number="configForm.session_memory_config.steps_between_updates"
                      min="0"
                    />
                  </div>
                </div>
              </div>

              <!-- 持久化记忆配置 -->
              <div class="section-box">
                <div class="section-title">
                  <span>🧠 持久化记忆配置</span>
                </div>
                <div class="switch-list">
                  <label class="switch-item">
                    <span>自动提取 (Auto Extract)</span>
                    <input type="checkbox" v-model="configForm.persistent_memory_config.auto_extract" />
                  </label>
                </div>
                <div class="form-grid">
                  <div class="field">
                    <label>最小消息数(初始化)</label>
                    <input
                      type="number"
                      v-model.number="configForm.persistent_memory_config.minimum_messages_to_init"
                      min="0"
                    />
                  </div>
                  <div class="field">
                    <label>更新间隔消息数</label>
                    <input
                      type="number"
                      v-model.number="configForm.persistent_memory_config.minimum_messages_between_update"
                      min="0"
                    />
                  </div>
                  <div class="field">
                    <label>更新 Step 数</label>
                    <input
                      type="number"
                      v-model.number="configForm.persistent_memory_config.steps_between_updates"
                      min="0"
                    />
                  </div>
                  <div class="field">
                    <label>新鲜度告警天数</label>
                    <input
                      type="number"
                      v-model.number="configForm.persistent_memory_config.freshness_warning_days"
                      min="0"
                    />
                  </div>
                </div>
              </div>

              <!-- 上下文压缩配置 -->
              <div class="section-box">
                <div class="section-title">
                  <span>📦 上下文压缩配置</span>
                </div>
                <div class="form-grid">
                  <div class="field">
                    <label>触发截断 Token 阈值</label>
                    <input type="number" v-model.number="configForm.compact_config.session_trunc_threshold" min="0" />
                  </div>
                  <div class="field">
                    <label>截断百分比</label>
                    <input
                      type="number"
                      v-model.number="configForm.compact_config.session_trunc_percentage"
                      min="0"
                      max="1"
                      step="0.1"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- 无配置信息提示 -->
            <div v-else class="empty-state">
              <p>暂无配置信息</p>
              <p class="hint">请选择一个 Agent 查看配置</p>
            </div>
          </div>
          <div class="dialog-footer">
            <button class="btn btn-secondary" @click="closeConfigDialog">关闭</button>
            <button class="btn btn-primary" :disabled="!agentConfig || saving" @click="saveConfig">
              {{ saving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.agent-sidebar {
  width: 260px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow-y: auto;
}

/* ==================== 标题栏 ==================== */
.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
  margin-bottom: 4px;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}

.auto-badge {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--success-fg);
  font-weight: 400;
}

.auto-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--success-fg);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.icon-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  padding: 2px 4px;
  border-radius: 3px;
}

.icon-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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

/* ==================== Agent 列表 ==================== */
.agent-list {
  flex: 1;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
}

.empty-agents {
  display: flex;
  justify-content: center;
  padding: 24px;
  color: var(--text-secondary);
  font-size: 12px;
}

/* ==================== Agent 卡片 ==================== */
.agent-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.agent-card:hover {
  border-color: var(--focus-border);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}
.card-main {
  border-color: var(--focus-border);
  border-width: 1.5px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.agent-info {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.type-icon {
  font-size: 18px;
  line-height: 1;
  flex-shrink: 0;
}

.agent-name-group {
  min-width: 0;
  flex: 1;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-role {
  font-size: 10px;
  color: var(--text-secondary);
  display: block;
}

.agent-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

/* ==================== 状态标签 ==================== */
.status-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  white-space: nowrap;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.dot-pulse {
  animation: pulse 1.2s ease-in-out infinite;
}

/* ==================== Abort 按钮 ==================== */
.abort-btn {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: var(--error-fg);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1;
}
.abort-btn:hover {
  background: rgba(239, 68, 68, 0.25);
}

/* ==================== 描述 ==================== */
.agent-desc {
  font-size: 11px;
  color: var(--text-secondary);
  margin: 6px 0 0;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ==================== 统计信息 ==================== */
.stats-section {
  display: grid;
  grid-template-columns: 1fr 1fr !important;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.03);
}

.stat-icon {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  flex-shrink: 0;
}

.stat-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.stat-label {
  font-size: 9px;
  color: var(--text-secondary);
  line-height: 1.1;
}
.stat-value {
  font-size: 11px;
  font-weight: 600;
  font-family: var(--code-font-family);
  line-height: 1.2;
}

/* ==================== 配置弹窗 ==================== */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.config-dialog {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  width: 500px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-color);
}

.dialog-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
}

.config-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.config-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.config-row:last-child {
  border-bottom: none;
}

.config-label {
  color: var(--text-secondary);
}

.config-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.config-value.mono {
  font-family: var(--code-font-family);
  font-size: 12px;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--border-color);
}

.btn {
  border: none;
  border-radius: 5px;
  padding: 7px 16px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}
.btn-secondary:hover {
  background: var(--border-color);
}
.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
}
.btn-primary:hover {
  background: var(--button-hover-bg);
}

/* ==================== 配置弹窗新样式 ==================== */

.config-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.loaded-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  background: rgba(34, 197, 94, 0.12);
  color: var(--success-fg);
  font-weight: 500;
}

.loading-state {
  text-align: center;
  padding: 24px 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.loading-state .hint {
  font-size: 11px;
  margin-top: 4px;
  opacity: 0.7;
}

.empty-state {
  text-align: center;
  padding: 24px 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.empty-state .hint {
  font-size: 11px;
  margin-top: 4px;
  opacity: 0.7;
}

.config-edit-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-box {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.section-title .hint {
  font-weight: 400;
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.7;
}

.llm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.field label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
}

.field select {
  width: 100%;
  padding: 6px 8px;
  background: var(--input-background, var(--bg-primary));
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.field select:focus {
  border-color: var(--focus-border);
}

.field select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ==================== 表单网格 ==================== */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.field.full {
  grid-column: 1 / -1;
}

.field input:not([type='checkbox']):not([type='radio']),
.field textarea {
  width: 100%;
  padding: 6px 8px;
  background: var(--input-background, var(--bg-primary));
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 12px;
  outline: none;
  font-family: inherit;
  box-sizing: border-box;
  resize: vertical;
}

.field input:not([type='checkbox']):not([type='radio']):focus,
.field textarea:focus {
  border-color: var(--focus-border);
}

.field input:not([type='checkbox']):not([type='radio']):disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ==================== 开关列表 ==================== */
.switch-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 4px;
}

.switch-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-primary);
  padding: 3px 0;
  cursor: pointer;
}

.switch-item input[type='checkbox'] {
  width: 15px;
  height: 15px;
  cursor: pointer;
  accent-color: var(--focus-border, #007fd4);
}

/* ==================== 工具多选下拉 ==================== */
.tools-select {
  position: relative;
  width: 100%;
}

.tools-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-height: 28px;
  padding: 4px 8px;
  background: var(--input-background, var(--bg-primary));
  border: 1px solid var(--border-color);
  border-radius: 4px;
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.tools-trigger:hover {
  border-color: var(--focus-border);
}

.tools-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.tool-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(0, 127, 212, 0.15);
  color: var(--text-link);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-tag-remove {
  cursor: pointer;
  font-weight: bold;
  color: var(--text-secondary);
  line-height: 1;
}

.tool-tag-remove:hover {
  color: var(--error-fg);
}

.tools-placeholder {
  color: var(--text-secondary);
  font-size: 12px;
  opacity: 0.7;
}

.tools-caret {
  color: var(--text-secondary);
  font-size: 11px;
  flex-shrink: 0;
}

.tools-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 210;
  background: var(--bg-primary, #252526);
  border: 1px solid var(--border-color, #3c3c3c);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}

.tools-search-row {
  padding: 6px;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
}

.tools-search {
  width: 100%;
  padding: 5px 8px;
  box-sizing: border-box;
  background: var(--input-background, var(--bg-primary));
  color: var(--text-primary);
  border: 1px solid var(--border-color, #3c3c3c);
  border-radius: 4px;
  font-size: 12px;
  outline: none;
}

.tools-search:focus {
  border-color: var(--focus-border, #007fd4);
}

.tools-add {
  padding: 4px 6px;
  border-bottom: 1px solid var(--border-color, #3c3c3c);
}

.tools-add-btn {
  width: 100%;
  text-align: left;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--text-link);
  background: transparent;
  border: 1px dashed var(--text-link);
  border-radius: 4px;
  cursor: pointer;
}

.tools-add-btn:hover {
  background: rgba(0, 127, 212, 0.12);
}

.tools-list {
  max-height: 160px;
  overflow-y: auto;
  padding: 4px 0;
}

.tools-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  white-space: nowrap;
}

.tools-option:hover {
  background: var(--list-hover-background, rgba(255, 255, 255, 0.06));
}

.tools-option input[type='checkbox'] {
  flex-shrink: 0;
  margin: 0;
  cursor: pointer;
  accent-color: var(--focus-border, #007fd4);
}

.section-box + .section-box {
  margin-top: 12px;
}

.config-textarea {
  width: 100%;
  min-height: 180px;
  padding: 10px 12px;
  background: #1e1e2e;
  color: #cdd6f4;
  border: 1px solid #45475a;
  border-radius: 6px;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 11px;
  line-height: 1.6;
  resize: vertical;
  tab-size: 2;
  outline: none;
}

.config-textarea:focus {
  border-color: var(--focus-border);
}

.btn-small {
  padding: 4px 10px;
  font-size: 11px;
}

/* ==================== Agent 消息过滤下拉 ==================== */
.filter-dropdown {
  position: relative;
}

.filter-btn {
  font-size: 14px;
}

.filter-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  min-width: 160px;
  max-height: 240px;
  overflow-y: auto;
  background: var(--bg-primary, #252526);
  border: 1px solid var(--border-color, #3c3c3c);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  z-index: 200;
  padding: 4px 0;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-primary, #cccccc);
  cursor: pointer;
  white-space: nowrap;
}

.filter-item:hover {
  background: var(--list-hover-background, rgba(255, 255, 255, 0.06));
}

.filter-item input[type='checkbox'] {
  flex-shrink: 0;
  margin: 0;
  cursor: pointer;
  accent-color: var(--focus-border, #007fd4);
}

.filter-item .truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .agent-sidebar {
    position: fixed;
    top: 0;
    left: -260px;
    bottom: 0;
    z-index: 100;
    transition: left 0.2s ease;
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.2);
  }
  .agent-sidebar.open {
    left: 0;
  }
  .close-btn {
    display: block;
  }
  .config-dialog {
    width: 100vw;
    max-width: 100vw;
    height: 100vh;
    max-height: 100vh;
    border-radius: 0;
  }
  .llm-grid {
    grid-template-columns: 1fr;
  }
}
</style>
