<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '../stores/chat'
import { postMessage } from '../api/vscode'

const chatStore = useChatStore()

const refreshing = ref(false)
const emit = defineEmits<{
  (e: 'openSearch'): void
}>()

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
      <!-- Search button -->
      <button
        class="search-btn"
        title="搜索消息"
        @click="emit('openSearch')"
      >🔍</button>
      <!-- Mode toggle -->
      <button
        class="mode-toggle-btn"
        :class="{ active: chatStore.displayMode === 'concise' }"
        :title="chatStore.displayMode === 'concise' ? '切换到明细模式' : '切换到简洁模式'"
        @click="chatStore.toggleDisplayMode()"
      >
        {{ chatStore.displayMode === 'concise' ? '简洁' : '明细' }}
      </button>
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

.connection-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.status-label {
  color: var(--text-secondary);
}

.search-btn {
  background: none;
  border: 1px solid transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  padding: 0 5px;
  border-radius: 3px;
  line-height: 1.5;
  transition: all 0.2s;
}

.search-btn:hover {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
  color: var(--text-primary);
}

.mode-toggle-btn {
  background: none;
  border: 1px solid transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  padding: 0 4px;
  border-radius: 3px;
  line-height: 1.5;
  margin-left: 4px;
  transition: all 0.2s;
}

.mode-toggle-btn:hover {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
  color: var(--text-primary);
}

.mode-toggle-btn.active {
  background: rgba(59, 130, 246, 0.1);
  border-color: var(--focus-border, #007acc);
  color: var(--vscode-textLink-foreground, #006ab1);
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
  margin-left: 4px;
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
