<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

interface AgentInfo {
  agent_id: string
  name: string
  status: 'idle' | 'running' | 'connecting' | 'disconnected'
}

// Derive agents from the agentNames map and defaultAgentId
const agents = computed<AgentInfo[]>(() => {
  return Object.entries(chatStore.agentNames).map(([id, name]) => ({
    agent_id: id,
    name,
    status: id === chatStore.defaultAgentId ? 'idle' : 'disconnected',
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
        class="agent-item"
        :class="{ 'agent-active': agent.agent_id === chatStore.defaultAgentId }"
      >
        <div class="agent-info">
          <span
            class="agent-status-dot"
            :style="{ background: getStatusDot(agent.status) }"
          ></span>
          <span class="agent-name">{{ agent.name }}</span>
        </div>
        <span class="agent-status-label">{{ getStatusLabel(agent.status) }}</span>
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
  cursor: pointer;
  margin-bottom: 2px;
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

.agent-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.agent-name {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-status-label {
  font-size: 10px;
  color: var(--text-secondary);
  flex-shrink: 0;
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
