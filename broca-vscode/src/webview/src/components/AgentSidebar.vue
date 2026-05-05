<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage } from '../api/vscode'

const chatStore = useChatStore()

const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  idle: { color: 'var(--success-fg)', bg: 'rgba(34,197,94,0.12)', label: '空闲' },
  running: { color: 'var(--focus-border)', bg: 'rgba(59,130,246,0.12)', label: '运行中' },
  connecting: { color: 'var(--warning-fg)', bg: 'rgba(234,179,8,0.12)', label: '连接中' },
  disconnected: { color: 'var(--text-secondary)', bg: 'rgba(156,163,175,0.12)', label: '断开' },
}

function getStatus(agentId: string | undefined): string {
  if (!agentId) return 'disconnected'
  const status = chatStore.agentStatuses[agentId]
  return status || 'disconnected'
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
      <div v-if="chatStore.agents.length === 0" class="empty-agents">
        No agents available
      </div>
      <div
        v-for="agent in chatStore.agents"
        :key="agent.agent_id"
        class="agent-card"
        :class="{ 'card-main': agent.agent_id === chatStore.defaultAgentId }"
      >
        <div class="card-header">
          <div class="agent-info">
            <span class="agent-name">{{ agent.name }}</span>
            <span class="agent-role">{{ agent.role || '' }}</span>
          </div>
          <div class="agent-actions">
            <span class="status-tag">
              <span class="status-dot"></span>
              {{ statusConfig[getStatus(agent.agent_id)]?.label || '断开' }}
            </span>
            <button
              v-if="getStatus(agent.agent_id) === 'running'"
              class="abort-btn"
              @click.stop="handleAbort(agent.agent_id)"
            >⏹</button>
          </div>
        </div>
      </div>
    </div>
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

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
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
  flex: 1;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
}

.empty-agents {
  display: flex;
  justify-content: center;
  padding: 24px;
  color: var(--text-secondary);
  font-size: 12px;
}

.agent-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
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
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-role {
  font-size: 10px;
  color: var(--text-secondary);
}

.agent-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.status-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  white-space: nowrap;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

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
}
</style>
