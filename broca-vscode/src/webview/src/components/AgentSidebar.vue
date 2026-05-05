<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

interface AgentDisplay {
  agent_id: string
  name: string
  status: 'idle' | 'running' | 'connecting' | 'disconnected'
  total_llm_calls: number
  total_input_tokens: number
  total_output_tokens: number
  last_context_length?: number
}

const agents = computed<AgentDisplay[]>(() => {
  return Object.entries(chatStore.agentNames).map(([id, name]) => {
    const fullData = chatStore.agentsData.find(a => a.agent_id === id)
    return {
      agent_id: id,
      name,
      status: chatStore.getAgentStatus(id),
      total_llm_calls: fullData?.total_llm_calls ?? 0,
      total_input_tokens: fullData?.total_input_tokens ?? 0,
      total_output_tokens: fullData?.total_output_tokens ?? 0,
      last_context_length: fullData?.last_context_length,
    }
  })
})

const statusConfig: Record<string, { color: string; label: string }> = {
  idle: { color: 'var(--success-fg)', label: '空闲' },
  running: { color: 'var(--focus-border)', label: '运行中' },
  connecting: { color: 'var(--warning-fg)', label: '连接中' },
  disconnected: { color: 'var(--text-secondary)', label: '断开' },
}

function getStatusLabel(status: string): string {
  return statusConfig[status]?.label || status
}

function handleAbort(agentId: string) {
  chatStore.sendAbort(agentId)
}

const isOpen = computed(() => chatStore.showLeftSidebar)
</script>

<template>
  <div class="agent-sidebar" :class="{ open: isOpen }">
    <div class="sidebar-header">
      <span class="sidebar-title">🤖 Agents</span>
      <button class="close-btn" @click="chatStore.toggleLeftSidebar()">✕</button>
    </div>

    <div class="agent-list">
      <div v-if="agents.length === 0" class="empty-agents">
        <span>No agents available</span>
      </div>

      <div
        v-for="agent in agents"
        :key="agent.agent_id"
        class="agent-card"
        :class="{ 'agent-main': agent.agent_id === chatStore.defaultAgentId }"
      >
        <!-- 顶栏：状态信息 + 操作 -->
        <div class="agent-top">
          <div class="agent-top-left">
            <span class="agent-status-dot" :class="'dot-' + agent.status"></span>
            <span class="agent-name">{{ agent.name }}</span>
          </div>
          <div class="agent-top-right">
            <button
              v-if="agent.status === 'running'"
              class="abort-btn"
              title="中止"
              @click.stop="handleAbort(agent.agent_id)"
            >
              ⏹
            </button>
            <span class="agent-status-label">{{ getStatusLabel(agent.status) }}</span>
          </div>
        </div>

        <!-- 统计信息行 -->
        <div class="agent-stats">
          <div class="agent-stat">
            <span class="agent-stat-icon">💬</span>
            <span class="agent-stat-value">{{ agent.total_llm_calls }}</span>
          </div>
          <div class="agent-stat">
            <span class="agent-stat-icon">📥</span>
            <span class="agent-stat-value">{{ agent.total_input_tokens.toLocaleString() }}</span>
          </div>
          <div class="agent-stat">
            <span class="agent-stat-icon">📤</span>
            <span class="agent-stat-value">{{ agent.total_output_tokens.toLocaleString() }}</span>
          </div>
          <div v-if="agent.last_context_length !== undefined" class="agent-stat">
            <span class="agent-stat-icon">📄</span>
            <span class="agent-stat-value">{{ agent.last_context_length.toLocaleString() }}</span>
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
  overflow-y: auto;
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

.agent-list {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.empty-agents {
  display: flex;
  justify-content: center;
  padding: 20px;
  color: var(--text-secondary);
  font-size: 12px;
}

/* ==================== Agent 卡片 ==================== */
.agent-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 8px 10px;
}

.agent-main {
  border-color: var(--focus-border);
}

/* 顶栏 */
.agent-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.agent-top-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.agent-top-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* 状态指示灯 */
.agent-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-idle { background: var(--success-fg); }
.dot-running {
  background: var(--focus-border);
  animation: pulse 1.2s ease-in-out infinite;
}
.dot-connecting {
  background: var(--warning-fg);
  animation: pulse 1.2s ease-in-out infinite;
}
.dot-disconnected { background: var(--text-secondary); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 3px;
  line-height: 1;
  display: flex;
  align-items: center;
}

.abort-btn:hover {
  background: rgba(239, 68, 68, 0.25);
}

/* ==================== 统计信息 ==================== */
.agent-stats {
  display: flex;
  gap: 10px;
  padding-top: 6px;
  border-top: 1px solid var(--border-color);
}

.agent-stat {
  display: flex;
  align-items: center;
  gap: 3px;
}

.agent-stat-icon {
  font-size: 10px;
  line-height: 1;
}

.agent-stat-value {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  font-family: var(--code-font-family);
}

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
