<script setup lang="ts">
import { computed, ref } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage } from '../api/vscode'

const chatStore = useChatStore()

const refreshing = ref(false)

const statusText = computed(() => {
  const info = chatStore.runnerInfo
  if (!info) return 'Checking...'
  switch (info.status) {
    case 'alive': return 'Running'
    case 'starting': return 'Starting...'
    case 'error': return `Error`
    case 'dead': return 'Stopped'
    default: return info.status
  }
})

const statusColor = computed(() => {
  const info = chatStore.runnerInfo
  if (!info) return 'var(--warning-fg)'
  switch (info.status) {
    case 'alive': return 'var(--success-fg)'
    case 'starting': return 'var(--warning-fg)'
    case 'error': return 'var(--error-fg)'
    default: return 'var(--text-secondary)'
  }
})

function handleRefresh() {
  if (refreshing.value) return
  refreshing.value = true
  postMessage({ type: 'refreshChat' })
  // Reset refresh spinner after a timeout
  setTimeout(() => { refreshing.value = false }, 3000)
}
</script>

<template>
  <div class="status-bar">
    <div class="status-left">
      <!-- Connection status -->
      <span
        class="connection-dot"
        :style="{ background: chatStore.connected ? 'var(--success-fg)' : 'var(--warning-fg)' }"
      ></span>
      <span class="status-label">
        {{ chatStore.connected ? 'Connected' : 'Connecting...' }}
      </span>
    </div>
    <div class="status-right">
      <!-- Runner status -->
      <span
        class="runner-dot"
        :style="{ background: statusColor }"
      ></span>
      <span class="status-label">{{ statusText }}</span>
      <!-- Refresh button -->
      <button
        class="refresh-btn"
        :class="{ refreshing: refreshing }"
        :disabled="refreshing"
        title="Refresh chat"
        @click="handleRefresh"
      >🔄</button>
    </div>
  </div>
</template>

<style scoped>
.status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  font-size: 11px;
  min-height: 24px;
}

.status-left,
.status-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.connection-dot,
.runner-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.status-label {
  color: var(--text-secondary);
}

.refresh-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  border-radius: 3px;
  line-height: 1;
  margin-left: 8px;
  transition: transform 0.2s;
}

.refresh-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.refresh-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.refresh-btn.refreshing {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
