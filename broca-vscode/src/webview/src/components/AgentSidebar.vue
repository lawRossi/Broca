<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

const agentRows = computed(() => {
  return Object.entries(chatStore.agentNames).map(([id, name]) => {
    const fullData = chatStore.agentsData.find(a => a.agent_id === id)
    return {
      agent_id: id,
      name,
      status: chatStore.getAgentStatus(id),
      total_input_tokens: fullData?.total_input_tokens,
      total_output_tokens: fullData?.total_output_tokens,
      total_llm_calls: fullData?.total_llm_calls,
      last_context_length: fullData?.last_context_length,
    }
  })
})

const statusLabels: Record<string, string> = {
  idle: '空闲',
  running: '运行中',
  connecting: '连接中',
  disconnected: '断开',
}

function handleAbort(agentId: string) {
  chatStore.sendAbort(agentId)
}
</script>

<template>
  <div class="agent-sidebar">
    <div class="sidebar-header">
      <span>🤖 Agents</span>
    </div>

    <div class="agent-list">
      <div v-if="agentRows.length === 0" class="empty-agents">
        No agents available
      </div>

      <div v-for="agent in agentRows" :key="agent.agent_id" class="agent-card">
        <!-- Row 1: status + name + abort -->
        <div class="agent-row">
          <div class="agent-info">
            <span class="status-dot" :class="'s-' + agent.status"></span>
            <span class="agent-name">{{ agent.name }}</span>
            <span class="status-text">{{ statusLabels[agent.status] || agent.status }}</span>
          </div>
          <button
            v-if="agent.status === 'running'"
            class="abort-btn"
            @click.stop="handleAbort(agent.agent_id)"
          >⏹ 中止</button>
        </div>

        <!-- Row 2: LLM stats -->
        <div class="stats-row">
          <span class="stat">💬 {{ agent.total_llm_calls || 0 }} 调用</span>
          <span class="stat">📥 {{ (agent.total_input_tokens || 0).toLocaleString() }} 输入</span>
          <span class="stat">📤 {{ (agent.total_output_tokens || 0).toLocaleString() }} 输出</span>
          <span v-if="agent.last_context_length !== undefined" class="stat">
            📄 {{ agent.last_context_length.toLocaleString() }} 上下文
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-sidebar {
  width: 220px;
  min-width: 220px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  padding: 10px 12px;
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.agent-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.empty-agents {
  padding: 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12px;
}

.agent-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
}

.agent-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.agent-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.s-idle { background: var(--success-fg); }
.s-running { background: var(--focus-border); }
.s-connecting { background: var(--warning-fg); }
.s-disconnected { background: var(--text-secondary); }

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-text {
  font-size: 10px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.abort-btn {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: var(--error-fg);
  cursor: pointer;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border-color);
  font-size: 10px;
  color: var(--text-secondary);
}

.stat {
  white-space: nowrap;
}
</style>
