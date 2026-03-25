<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores'
import ChatMessageItem from './ChatMessageItem.vue'

const chatStore = useChatStore()
const containerRef = ref<HTMLElement>()

const scrollToBottom = () => {
  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}

watch(() => chatStore.messages.length, () => {
  if (!chatStore.loadingMore) {
    scrollToBottom()
  }
})

const handleScroll = (event: Event) => {
  const target = event.target as HTMLElement
  if (target.scrollTop < 50) {
    chatStore.loadHistory(chatStore.sessionId, true)
  }
}
</script>

<template>
  <div
    ref="containerRef"
    class="flex-1 bg-white rounded-lg border shadow-sm overflow-y-auto p-4 space-y-3"
    @scroll="handleScroll"
  >
    <div v-if="chatStore.loadingMore" class="flex items-center justify-center py-2 text-gray-400 text-sm">
      <span class="mr-2">加载中...</span>
    </div>
    <div v-else-if="!chatStore.hasMoreHistory && chatStore.messages.length > 0" class="flex items-center justify-center py-2 text-gray-400 text-sm">
      <span>没有更多历史消息了</span>
    </div>
    
    <div v-if="!chatStore.messages.length" class="flex flex-col items-center justify-center h-full text-gray-400">
      <div class="text-4xl mb-2">
        💬
      </div>
      <div v-if="chatStore.urlSessionId && !chatStore.connected" class="text-sm">
        正在自动连接...
      </div>
      <div v-else-if="chatStore.urlSessionId && chatStore.connected" class="text-sm">
        已连接，等待消息...
      </div>
      <div v-else class="text-sm">
        未设置session_id。请手动输入或通过URL参数传入。
      </div>
    </div>

    <ChatMessageItem
      v-for="m in chatStore.messages"
      :key="m.message_id"
      :message="m"
    />
  </div>
</template>
