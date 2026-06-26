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
const editableConfigContent = ref<string>('')
const selectedProvider = ref<string>('')
const selectedModel = ref<string>('')
const availableProviders = ref<{ id: string; name: string }[]>([])
const availableModels = ref<{ id: string; name: string }[]>([])
const saving = ref(false)

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
  editableConfigContent.value = ''
  selectedProvider.value = ''
  selectedModel.value = ''
  // 关闭弹窗后，仅在 runner 运行时恢复自动刷新
  if (chatStore.sessionId && chatStore.runnerAlive) {
    startAutoRefresh(30000)
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

  editableConfigContent.value = JSON.stringify(agentConfig.value.config_content, null, 2)

  const config = agentConfig.value.config_content
  selectedProvider.value = config.provider || ''
  selectedModel.value = config.model || ''

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

function saveConfig() {
  if (!selectedAgent.value || !agentConfig.value) return

  saving.value = true
  try {
    let configContent: Record<string, any>
    try {
      configContent = JSON.parse(editableConfigContent.value)
    } catch (e) {
      chatStore.showError('配置内容 JSON 格式有误，请检查后重试', 'error')
      return
    }

    if (selectedProvider.value) {
      configContent.provider = selectedProvider.value
    }
    if (selectedModel.value) {
      configContent.model = selectedModel.value
    }

    postMessage({
      type: 'updateAgentConfig',
      payload: {
        agentId: selectedAgent.value.agent_id,
        config_content: configContent,
      },
    })
  } finally {
    saving.value = false
  }
}

// ==================== 监听来自 Extension 的消息 ====================
const unsubMessage = ref<(() => void) | null>(null)

function handleDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.filter-dropdown')) {
    showFilterDropdown.value = false
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
        break
    }
  })

  if (chatStore.sessionId && chatStore.runnerAlive) startAutoRefresh(30000)
})

// 监听 Runner 状态变化，控制自动刷新启停
watch(
  () => chatStore.runnerAlive,
  (isAlive) => {
    if (isAlive && chatStore.sessionId) {
      startAutoRefresh(30000)
    } else {
      stopAutoRefresh()
    }
  },
  { immediate: true }
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

function startAutoRefresh(intervalMs: number = 30000) {
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
    if (newId && chatStore.runnerAlive) startAutoRefresh(30000)
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
        <div class="filter-dropdown" v-if="sortedAgents.length > 0">
          <button class="icon-btn filter-btn" title="过滤Agent消息" @click="showFilterDropdown = !showFilterDropdown">⚙️</button>
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
      <div v-if="sortedAgents.length === 0" class="empty-agents">
        No agents available
      </div>
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
              <span
                class="status-dot"
                :class="{ 'dot-pulse': getStatus(agent.agent_id) === 'running' }"
              ></span>
              {{ statusConfig[getStatus(agent.agent_id)]?.label || '断开' }}
            </span>
            <button
              v-if="getStatus(agent.agent_id) === 'running'"
              class="abort-btn"
              title="中断此 Agent"
              @click.stop="handleAbort(agent.agent_id)"
            >⏹</button>
          </div>
        </div>

        <!-- 描述 -->
        <p v-if="agent.description" class="agent-desc">{{ agent.description }}</p>

        <!-- LLM 统计信息 -->
        <div class="stats-section">
          <div class="stat-item">
            <span class="stat-icon" style="background:rgba(59,130,246,0.12)">💬</span>
            <div class="stat-text">
              <span class="stat-label">调用次数</span>
              <span class="stat-value" style="color:var(--text-link)">{{ agent.total_llm_calls || 0 }}</span>
            </div>
          </div>
          <div v-if="agent.last_context_length !== undefined" class="stat-item">
            <span class="stat-icon" style="background:rgba(168,85,247,0.12)">📄</span>
            <div class="stat-text">
              <span class="stat-label">上下文</span>
              <span class="stat-value" style="color:#a855f7">{{ agent.last_context_length || 0 }}</span>
            </div>
          </div>
          <div class="stat-item">
            <span class="stat-icon" style="background:rgba(34,197,94,0.12)">⬇️</span>
            <div class="stat-text">
              <span class="stat-label">输入 Token</span>
              <span class="stat-value" style="color:var(--success-fg)">{{ (agent.total_input_tokens || 0).toLocaleString() }}</span>
            </div>
          </div>
          <div class="stat-item">
            <span class="stat-icon" style="background:rgba(234,179,8,0.12)">⬆️</span>
            <div class="stat-text">
              <span class="stat-label">输出 Token</span>
              <span class="stat-value" style="color:var(--warning-fg)">{{ (agent.total_output_tokens || 0).toLocaleString() }}</span>
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
              <button class="btn btn-secondary btn-small" @click="refreshConfig" :disabled="configLoading">
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

              <!-- 可编辑的配置内容 -->
              <div class="section-box">
                <div class="section-title">
                  <span>📄 配置内容 (config_content)</span>
                  <span class="hint">- 可编辑 JSON</span>
                </div>
                <textarea
                  v-model="editableConfigContent"
                  class="config-textarea"
                  rows="12"
                  placeholder="在此编辑配置 JSON..."
                  spellcheck="false"
                ></textarea>
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
            <button
              class="btn btn-primary"
              :disabled="!agentConfig || saving"
              @click="saveConfig"
            >
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
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
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

.icon-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }

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
.close-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }

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
.card-main { border-color: var(--focus-border); border-width: 1.5px; }

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

.type-icon { font-size: 18px; line-height: 1; flex-shrink: 0; }

.agent-name-group { min-width: 0; flex: 1; }

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

.status-dot { width: 6px; height: 6px; border-radius: 50%; }
.dot-pulse { animation: pulse 1.2s ease-in-out infinite; }

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
.abort-btn:hover { background: rgba(239, 68, 68, 0.25); }

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

.stat-text { display: flex; flex-direction: column; min-width: 0; }
.stat-label { font-size: 9px; color: var(--text-secondary); line-height: 1.1; }
.stat-value { font-size: 11px; font-weight: 600; font-family: var(--code-font-family); line-height: 1.2; }

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

.dialog-title { font-weight: 600; font-size: 14px; color: var(--text-primary); }

.dialog-body { flex: 1; overflow-y: auto; padding: 16px 18px; }

.config-content { display: flex; flex-direction: column; gap: 8px; }

.config-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.config-row:last-child { border-bottom: none; }

.config-label { color: var(--text-secondary); }

.config-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.config-value.mono { font-family: var(--code-font-family); font-size: 12px; }

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

.btn-secondary { background: var(--bg-tertiary); color: var(--text-primary); border: 1px solid var(--border-color); }
.btn-secondary:hover { background: var(--border-color); }
.btn-primary { background: var(--button-bg); color: var(--button-text); }
.btn-primary:hover { background: var(--button-hover-bg); }

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

.filter-item input[type="checkbox"] {
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
  .agent-sidebar.open { left: 0; }
  .close-btn { display: block; }
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
