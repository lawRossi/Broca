<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import ChatMessageItem from './ChatMessageItem.vue'

const chatStore = useChatStore()
const containerRef = ref<HTMLElement>()
const scrollTimeout = ref<number | null>(null)
const isAutoScrolling = ref(false)

const scrollToBottom = () => {
  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}

const handleScroll = () => {
  const container = containerRef.value
  if (!container) return

  if (scrollTimeout.value) clearTimeout(scrollTimeout.value)

  scrollTimeout.value = window.setTimeout(() => {
    if (container.scrollTop < 50 && !chatStore.loadingMore && chatStore.hasMoreHistory) {
      chatStore.loadMoreHistory()
    }
  }, 200)
}

// Watch messages for auto-scroll
watch(
  () => chatStore.messages.length,
  () => {
    scrollToBottom()
  }
)

// Also watch for agent_response content changes (streaming updates)
watch(
  () => chatStore.messages.map(m => m.data?.content).join(''),
  () => {
    scrollToBottom()
  }
)

onMounted(() => {
  scrollToBottom()
})

onUnmounted(() => {
  if (scrollTimeout.value) clearTimeout(scrollTimeout.value)
})
</script>

<template>
  <div
    ref="containerRef"
    class="message-list"
    @scroll="handleScroll"
  >
    <!-- Loading more indicator -->
    <div v-if="chatStore.loadingMore" class="load-more-indicator">
      Loading more...
    </div>

    <!-- Empty state -->
    <div v-if="chatStore.messages.length === 0 && !chatStore.loading" class="empty-state">
      <div class="empty-icon">💬</div>
      <div v-if="!chatStore.connected" class="empty-text">Connecting...</div>
      <div v-else class="empty-text">Connected. Send a message to get started.</div>
    </div>

    <!-- Message list -->
    <div v-for="m in chatStore.messages" :key="m.message_id" class="message-wrapper">
      <ChatMessageItem :message="m" />
    </div>

    <!-- Redo button -->
    <div v-if="chatStore.showRedoButton" class="redo-container">
      <button class="redo-button" @click="chatStore.sendRedo()">
        ↩️ Redo
      </button>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  height: 100%;
  overflow-y: auto;
  padding: 12px 16px;
}

.load-more-indicator {
  text-align: center;
  padding: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-text {
  font-size: 14px;
}

.message-wrapper {
  margin-bottom: 8px;
}

.redo-container {
  display: flex;
  justify-content: center;
  padding: 8px 0;
}

.redo-button {
  background: var(--button-bg);
  color: var(--button-text);
  border: none;
  border-radius: 12px;
  padding: 4px 16px;
  font-size: 12px;
  cursor: pointer;
}

.redo-button:hover {
  background: var(--button-hover-bg);
}
</style>
