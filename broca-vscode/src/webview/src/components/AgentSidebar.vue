<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '../stores/chat'

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

function getTypeColor(type: string | undefined): string {
  const colors: Record<string, string> = {
    assistant: 'var(--text-link)',
    code_assistant: 'var(--success-fg)',
    research_assistant: 'var(--warning-fg)',
    task_manager: '#a855f7',
    data_analyst: '#06b6d4',
  }
  return colors[type || 'assistant'] || 'var(--text-link)'
}

// ==================== 选中的 Agent 配置弹窗 ====================
const showConfigDialog = ref(false)
const selectedAgent = ref<any>(null)

function handleAgentClick(agent: any) {
  selectedAgent.value = agent
  showConfigDialog.value = true
}

function closeConfigDialog() {
  showConfigDialog.value = false
  selectedAgent.value = null
}

function sendMessageToAgent() {
  if (!selectedAgent.value) return
  const agentName = selectedAgent.value.name || selectedAgent.value.agent_id
  chatStore.inputText = `@${agentName} `
  closeConfigDialog()
}

// ==================== 自动刷新 ====================
const autoRefreshInterval = ref<number | null>(null)
const loading = ref(false)
const lastRefreshTime = ref<Date>(new Date())

async function refreshAgents() {
  loading.value = true
  // Request agent refresh from extension host
  const { postMessage } = await import('../api/vscode')
  postMessage({
    type: 'fetchAgents',
    payload: { sessionId: chatStore.sessionId },
  })
  lastRefreshTime.value = new Date()
  loading.value = false
}

function startAutoRefresh(intervalMs: number = 10000) {
  if (autoRefreshInterval.value) stopAutoRefresh()
  autoRefreshInterval.value = window.setInterval(() => {
    if (chatStore.sessionId) {
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
    if (newId) startAutoRefresh(30000)
    else stopAutoRefresh()
  }
)

onMounted(() => {
  if (chatStore.sessionId) startAutoRefresh(30000)
})

onUnmounted(() => {
  stopAutoRefresh()
})

// ==================== 侧栏状态 ====================
const isOpen = computed(() => chatStore.showLeftSidebar)
</script>

<template>
  <div class="agent-sidebar" :class="{ open: isOpen }">
    <!-- 标题栏 -->
    <div class="sidebar-header">
      <div class="header-title">
        <span>🤖 Agents</span>
        <span v-if="autoRefreshInterval" class="auto-badge" title="自动刷新已开启 (30秒)">
          <span class="auto-dot"></span>
          <span class="auto-text">自动</span>
        </span>
      </div>
      <div class="header-actions">
        <button class="icon-btn" title="刷新 Agent 列表" :disabled="loading" @click="refreshAgents">
          🔄
        </button>
        <button class="close-btn" @click="chatStore.toggleLeftSidebar()">✕</button>
      </div>
    </div>

    <!-- Agent 列表 -->
    <div class="agent-list">
      <div v-if="chatStore.agents.length === 0" class="empty-agents">
        <span>No agents available</span>
      </div>

      <div
        v-for="agent in chatStore.agents"
        :key="agent.agent_id"
        class="agent-card"
        :class="{ 'card-main': agent.agent_id === chatStore.defaultAgentId }"
        @click="handleAgentClick(agent)"
      >
        <!-- Agent 头部 -->
        <div class="card-header">
          <div class="agent-info">
            <span class="type-icon" :style="{ color: getTypeColor(agent.type) }">{{ getTypeIcon(agent.type) }}</span>
            <div class="agent-name-group">
              <span class="agent-name">{{ agent.name }}</span>
              <span class="agent-role">{{ agent.role || '未指定' }}</span>
            </div>
          </div>
          <div class="agent-actions">
            <!-- 状态标签 -->
            <span
              class="status-tag"
              :style="{
                color: statusConfig[getAgentRuntimeStatus(agent.agent_id)]?.color,
                background: statusConfig[getAgentRuntimeStatus(agent.agent_id)]?.bg,
              }"
            >
              <span
                class="status-dot"
                :class="{ 'dot-pulse': getAgentRuntimeStatus(agent.agent_id) === 'running' }"
                :style="{ background: statusConfig[getAgentRuntimeStatus(agent.agent_id)]?.color }"
              ></span>
              {{ statusConfig[getAgentRuntimeStatus(agent.agent_id)]?.label || '断开' }}
            </span>
            <!-- Abort 按钮 -->
            <button
              v-if="getAgentRuntimeStatus(agent.agent_id) === 'running'"
              class="abort-btn"
              title="中断此 Agent"
              @click.stop="chatStore.sendAbort(agent.agent_id)"
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
            <span class="stat-icon" style="background: rgba(59,130,246,0.12)">💬</span>
            <div class="stat-text">
              <span class="stat-label">调用次数</span>
              <span class="stat-value" style="color: var(--text-link)">{{ agent.total_llm_calls || 0 }}</span>
            </div>
          </div>
          <div v-if="agent.last_context_length !== undefined" class="stat-item">
            <span class="stat-icon" style="background: rgba(168,85,247,0.12)">📄</span>
            <div class="stat-text">
              <span class="stat-label">上下文</span>
              <span class="stat-value" style="color: #a855f7">{{ agent.last_context_length?.toLocaleString() }}</span>
            </div>
          </div>
          <div class="stat-item">
            <span class="stat-icon" style="background: rgba(34,197,94,0.12)">📈</span>
            <div class="stat-text">
              <span class="stat-label">输入 Token</span>
              <span class="stat-value" style="color: var(--success-fg)">{{ (agent.total_input_tokens || 0).toLocaleString() }}</span>
            </div>
          </div>
          <div class="stat-item">
            <span class="stat-icon" style="background: rgba(234,179,8,0.12)">📊</span>
            <div class="stat-text">
              <span class="stat-label">输出 Token</span>
              <span class="stat-value" style="color: var(--warning-fg)">{{ (agent.total_output_tokens || 0).toLocaleString() }}</span>
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
            <div v-if="selectedAgent" class="config-content">
              <div class="config-row">
                <span class="config-label">Agent ID</span>
                <span class="config-value mono">{{ selectedAgent.agent_id }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">名称</span>
                <span class="config-value">{{ selectedAgent.name }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">角色</span>
                <span class="config-value">{{ selectedAgent.role || '未指定' }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">类型</span>
                <span class="config-value">{{ selectedAgent.type || 'assistant' }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">描述</span>
                <span class="config-value">{{ selectedAgent.description || '暂无描述' }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">调用次数</span>
                <span class="config-value">{{ selectedAgent.total_llm_calls || 0 }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">输入 Token</span>
                <span class="config-value">{{ (selectedAgent.total_input_tokens || 0).toLocaleString() }}</span>
              </div>
              <div class="config-row">
                <span class="config-label">输出 Token</span>
                <span class="config-value">{{ (selectedAgent.total_output_tokens || 0).toLocaleString() }}</span>
              </div>
            </div>
          </div>
          <div class="dialog-footer">
            <button class="btn btn-secondary" @click="closeConfigDialog">关闭</button>
            <button class="btn btn-primary" @click="sendMessageToAgent">发送消息给此 Agent</button>
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

.auto-text {
  opacity: 0.8;
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
  gap: 8px;
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
  padding: 10px 12px;
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

/* ==================== 卡片头部 ==================== */
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
  grid-template-columns: 1fr 1fr;
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
}
</style>
