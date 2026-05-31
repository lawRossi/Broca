<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import ChatMessageItem from './ChatMessageItem.vue'

const chatStore = useChatStore()
const containerRef = ref<HTMLElement>()
const scrollTimeout = ref<number | null>(null)
const isRestoringScroll = ref(false)

// ==================== 滚动位置保持 ====================
function saveScrollState() {
  if (!containerRef.value) return null
  return {
    scrollTop: containerRef.value.scrollTop,
    scrollHeight: containerRef.value.scrollHeight,
    clientHeight: containerRef.value.clientHeight,
  }
}

function restoreScrollState(prevState: any) {
  if (!containerRef.value || !prevState) return

  isRestoringScroll.value = true
  nextTick(() => {
    const container = containerRef.value!
    const newScrollHeight = container.scrollHeight
    const heightDiff = newScrollHeight - prevState.scrollHeight

    container.scrollTop = prevState.scrollTop + heightDiff

    if (scrollTimeout.value) clearTimeout(scrollTimeout.value)
    scrollTimeout.value = window.setTimeout(() => {
      isRestoringScroll.value = false
      scrollTimeout.value = null
    }, 150)
  })
}

const scrollToBottom = () => {
  if (isRestoringScroll.value) return

  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}

// ==================== 自动滚动 ====================
watch(
  () => chatStore.filteredMessages.length,
  () => {
    if (isRestoringScroll.value) return
    if (!chatStore.loadingMore) {
      scrollToBottom()
    }
  }
)

// Also watch for agent_response content changes (streaming updates)
watch(
  () => chatStore.messages.map(m => m.data?.content).join(''),
  () => {
    if (isRestoringScroll.value) return
    scrollToBottom()
  }
)

// ==================== 滚动加载更多 ====================
const handleScroll = () => {
  const container = containerRef.value
  if (!container) return

  if (scrollTimeout.value) clearTimeout(scrollTimeout.value)

  scrollTimeout.value = window.setTimeout(() => {
    if (container.scrollTop < 50 && !chatStore.loadingMore && chatStore.hasMoreHistory) {
      const scrollState = saveScrollState()
      chatStore.loadMoreHistory()

      // Try to restore scroll position after a short delay
      setTimeout(() => {
        restoreScrollState(scrollState)
      }, 300)
    }
  }, 200)
}

// ==================== 生命周期 ====================
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
      <span>加载中...</span>
    </div>
    <div
      v-else-if="!chatStore.hasMoreHistory && chatStore.filteredMessages.length > 0"
      class="flex items-center justify-center py-2 text-gray-400 text-sm"
    >
      <span>没有更多历史消息了</span>
    </div>

    <div v-if="chatStore.filteredMessages.length === 0 && !chatStore.loading" class="empty-state">
      <div class="empty-icon">💬</div>
      <div v-if="chatStore.sessionId && !chatStore.connected" class="empty-text">正在自动连接...</div>
      <div v-else-if="chatStore.sessionId && chatStore.connected" class="empty-text">已连接，等待消息...</div>
      <div v-else class="empty-text">未设置 session_id。请通过 URL 参数传入。</div>
    </div>

    <!-- Message list -->
    <div v-for="m in chatStore.filteredMessages" :key="m.message_id" class="message-wrapper">
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

.end-text {
  opacity: 0.6;
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
  margin-bottom: 6px;
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
