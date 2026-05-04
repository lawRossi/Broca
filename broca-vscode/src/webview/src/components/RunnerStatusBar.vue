<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

const statusText = computed(() => {
  const info = chatStore.runnerInfo
  if (!info) return 'Unknown'
  switch (info.status) {
    case 'alive': return 'Running'
    case 'starting': return 'Starting...'
    case 'error': return `Error: ${info.error_message || 'Unknown error'}`
    case 'dead': return 'Stopped'
    default: return info.status
  }
})

const statusColor = computed(() => {
  const info = chatStore.runnerInfo
  if (!info) return 'var(--text-secondary)'
  switch (info.status) {
    case 'alive': return 'var(--success-fg)'
    case 'starting': return 'var(--warning-fg)'
    case 'error': return 'var(--error-fg)'
    default: return 'var(--text-secondary)'
  }
})
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
</style>
