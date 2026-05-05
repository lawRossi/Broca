<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

interface AgentInfo {
  agent_id: string
  name: string
  status: 'idle' | 'running' | 'connecting' | 'disconnected'
}

// Derive agents from agentNames with real-time status from store
const agents = computed<AgentInfo[]>(() => {
  return Object.entries(chatStore.agentNames).map(([id, name]) => ({
    agent_id: id,
    name,
    status: chatStore.getAgentStatus(id),
  }))
})

const statusConfig: Record<string, { color: string; label: string }> = {
  idle: { color: 'var(--success-fg)', label: '空闲' },
  running: { color: 'var(--focus-border)', label: '运行中' },
  connecting: { color: 'var(--warning-fg)', label: '连接中' },
  disconnected: { color: 'var(--text-secondary)', label: '断开' },
}

function getStatusDot(status: string): string {
  return statusConfig[status]?.color || 'var(--text-secondary)'
}

function getStatusLabel(status: string): string {
  return statusConfig[status]?.label || status
}

function handleAbort(agentId: string) {
  chatStore.sendAbort(agentId)
}

function handleSelectAgent(agentId: string) {
  chatStore.selectAgent(agentId)
}

const isOpen = computed(() => chatStore.showLeftSidebar)
</script>

<template>
  <div class="agent-sidebar" :class="{ open: isOpen }">
    <div class="sidebar-header">
      <span class="sidebar-title">🤖 Agents</span>
      <button class="close-btn" @click="chatStore.toggleLeftSidebar()">✕</button>
    </div>

    <div class="sidebar-body">
      <!-- Agent 列表 -->
      <div class="agent-list">
        <div v-if="agents.length === 0" class="empty-agents">
          <span>No agents available</span>
        </div>
        <div
          v-for="agent in agents"
          :key="agent.agent_id"
          class="agent-item"
          :class="{
            'agent-active': agent.agent_id === chatStore.selectedAgentId,
          }"
          @click="handleSelectAgent(agent.agent_id)"
        >
          <div class="agent-info">
            <span
              class="agent-status-dot"
              :class="'dot-' + agent.status"
            ></span>
            <span class="agent-name">{{ agent.name }}</span>
          </div>
          <div class="agent-actions">
            <button
              v-if="agent.status === 'running'"
              class="abort-btn"
              title="中止该 Agent"
              @click.stop="handleAbort(agent.agent_id)"
            >
              ⏹
            </button>
            <span class="agent-status-label">{{ getStatusLabel(agent.status) }}</span>
          </div>
        </div>
      </div>

      <!-- 选中 Agent 详情 -->
      <div v-if="chatStore.selectedAgent" class="agent-detail">
        <div class="detail-divider"></div>
        <div class="detail-header">
          <span class="detail-title">{{ chatStore.selectedAgent.name || chatStore.selectedAgent.agent_id }}</span>
          <span v-if="chatStore.selectedAgent.type" class="detail-type">{{ chatStore.selectedAgent.type }}</span>
        </div>
        <p v-if="chatStore.selectedAgent.description" class="detail-desc">
          {{ chatStore.selectedAgent.description }}
        </p>

        <!-- LLM 统计信息 -->
        <div class="llm-stats">
          <div class="stats-grid">
            <!-- 调用次数 -->
            <div class="stat-item">
              <div class="stat-icon icon-blue">💬</div>
              <div class="stat-info">
                <span class="stat-label">调用次数</span>
                <span class="stat-value blue">{{ chatStore.selectedAgent.total_llm_calls || 0 }}</span>
              </div>
            </div>
            <!-- 上下文长度 -->
            <div v-if="chatStore.selectedAgent.last_context_length !== undefined" class="stat-item">
              <div class="stat-icon icon-purple">📄</div>
              <div class="stat-info">
                <span class="stat-label">上下文</span>
                <span class="stat-value purple">{{ (chatStore.selectedAgent.last_context_length ?? 0).toLocaleString() }}</span>
              </div>
            </div>
            <!-- 输入 Token -->
            <div class="stat-item">
              <div class="stat-icon icon-green">📥</div>
              <div class="stat-info">
                <span class="stat-label">输入 Token</span>
                <span class="stat-value green">{{ (chatStore.selectedAgent.total_input_tokens || 0).toLocaleString() }}</span>
              </div>
            </div>
            <!-- 输出 Token -->
            <div class="stat-item">
              <div class="stat-icon icon-orange">📤</div>
              <div class="stat-info">
                <span class="stat-label">输出 Token</span>
                <span class="stat-value orange">{{ (chatStore.selectedAgent.total_output_tokens || 0).toLocaleString() }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-sidebar {
  width: 220px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
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

.sidebar-body {
  flex: 1;
  overflow-y: auto;
}

/* ==================== Agent 列表 ==================== */
.agent-list {
  padding: 8px;
}

.empty-agents {
  display: flex;
  justify-content: center;
  padding: 20px;
  color: var(--text-secondary);
  font-size: 12px;
}

.agent-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  margin-bottom: 2px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.agent-item:hover {
  background: var(--bg-tertiary);
}

.agent-active {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
}

.agent-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

/* 状态指示灯 */
.agent-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-idle {
  background: var(--success-fg);
}

.dot-running {
  background: var(--focus-border);
  animation: pulse 1.2s ease-in-out infinite;
}

.dot-connecting {
  background: var(--warning-fg);
  animation: pulse 1.2s ease-in-out infinite;
}

.dot-disconnected {
  background: var(--text-secondary);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.agent-name {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.agent-status-label {
  font-size: 10px;
  color: var(--text-secondary);
}

/* Abort 按钮 */
.abort-btn {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: var(--error-fg);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1;
  display: flex;
  align-items: center;
}

.abort-btn:hover {
  background: rgba(239, 68, 68, 0.25);
}

/* ==================== Agent 详情 ==================== */
.detail-divider {
  height: 1px;
  background: var(--border-color);
  margin: 0 8px;
}

.agent-detail {
  padding: 10px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.detail-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-type {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.detail-desc {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin-bottom: 8px;
}

/* ==================== LLM 统计 ==================== */
.llm-stats {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 8px;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-icon {
  font-size: 14px;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  flex-shrink: 0;
}

.icon-blue { background: rgba(59, 130, 246, 0.15); }
.icon-purple { background: rgba(168, 85, 247, 0.15); }
.icon-green { background: rgba(34, 197, 94, 0.15); }
.icon-orange { background: rgba(251, 146, 60, 0.15); }

.stat-info {
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
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-value.blue { color: #60a5fa; }
.stat-value.purple { color: #c084fc; }
.stat-value.green { color: #4ade80; }
.stat-value.orange { color: #fb923c; }

/* Mobile responsive */
@media (max-width: 768px) {
  .agent-sidebar {
    position: fixed;
    top: 0;
    left: -220px;
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
}
</style>
