<script setup lang="ts">
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { useChatStore, useSocketStore } from '@/stores'
import ChatMessageItem from './ChatMessageItem.vue'

const chatStore = useChatStore()
const socketStore = useSocketStore()
const containerRef = ref<HTMLElement>()
const isRestoringScroll = ref(false)
const scrollTimeout = ref<number | null>(null)

const saveScrollState = () => {
  if (!containerRef.value) return null
  return {
    scrollTop: containerRef.value.scrollTop,
    scrollHeight: containerRef.value.scrollHeight,
    clientHeight: containerRef.value.clientHeight,
  }
}

const restoreScrollState = (prevState: any) => {
  if (!containerRef.value || !prevState) return

  isRestoringScroll.value = true
  nextTick(() => {
    const container = containerRef.value!
    const newScrollHeight = container.scrollHeight
    const heightDiff = newScrollHeight - prevState.scrollHeight

    container.scrollTop = prevState.scrollTop + heightDiff

    if (scrollTimeout.value) clearTimeout(scrollTimeout.value)
    scrollTimeout.value = setTimeout(() => {
      isRestoringScroll.value = false
      scrollTimeout.value = null
    }, 150) as unknown as number
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

watch(
  () => chatStore.messages.length,
  () => {
    if (isRestoringScroll.value) return

    if (!chatStore.loadingMore) {
      scrollToBottom()
    }
  }
)

const handleScroll = (event: Event) => {
  const target = event.target as HTMLElement

  if (scrollTimeout.value) clearTimeout(scrollTimeout.value)

  scrollTimeout.value = setTimeout(() => {
    if (target.scrollTop < 50 && !chatStore.loadingMore && chatStore.hasMoreHistory) {
      const scrollState = saveScrollState()

      chatStore
        .loadHistory(chatStore.sessionId, true, chatStore.executionId)
        .then(() => {
          restoreScrollState(scrollState)
        })
        .catch((error) => {
          console.error('加载历史消息失败:', error)
          isRestoringScroll.value = false
        })
    }
  }, 200) as unknown as number
}

onUnmounted(() => {
  if (scrollTimeout.value) {
    clearTimeout(scrollTimeout.value)
  }
})

// 发送重做命令
const handleRedo = () => {
  socketStore.sendRedo({
    receiverId: chatStore.redoReceiverId,
  })
  chatStore.showRedoButton = false
  chatStore.redoReceiverId = undefined
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
    <div
      v-else-if="!chatStore.hasMoreHistory && chatStore.messages.length > 0"
      class="flex items-center justify-center py-2 text-gray-400 text-sm"
    >
      <span>没有更多历史消息了</span>
    </div>

    <div v-if="!chatStore.messages.length" class="flex flex-col items-center justify-center h-full text-gray-400">
      <div class="text-4xl mb-2">💬</div>
      <div v-if="chatStore.urlSessionId && !chatStore.connected" class="text-sm">正在自动连接...</div>
      <div v-else-if="chatStore.urlSessionId && chatStore.connected" class="text-sm">已连接，等待消息...</div>
      <div v-else class="text-sm">未设置session_id。请手动输入或通过URL参数传入。</div>
    </div>

    <ChatMessageItem v-for="m in chatStore.messages" :key="m.message_id" :message="m" />

    <!-- 重做按钮 - 撤销成功后显示 -->
    <div
      v-if="chatStore.showRedoButton"
      class="flex justify-center py-2"
    >
      <el-button
        type="warning"
        size="small"
        @click="handleRedo"
        class="!rounded-full !px-4"
      >
        <span class="flex items-center gap-1">
          <span>↪️</span>
          <span>重做</span>
        </span>
      </el-button>
    </div>
  </div>
</template>
