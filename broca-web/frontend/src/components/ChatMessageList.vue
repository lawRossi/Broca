<script setup lang="ts">
import { ref, watch, nextTick, onUnmounted, computed } from 'vue'
import { useChatStore, useSocketStore } from '@/stores'
import ChatMessageItem from './ChatMessageItem.vue'
import ChatTurnCard from './ChatTurnCard.vue'

const chatStore = useChatStore()
const socketStore = useSocketStore()
const containerRef = ref<HTMLElement>()
const isRestoringScroll = ref(false)

// 简洁模式状态
const isConciseMode = computed(() => chatStore.displayMode === 'concise')

// 模式切换时保存/恢复滚动位置
let previousScrollPct = 0
watch(() => chatStore.displayMode, (newMode, oldMode) => {
  if (oldMode === newMode || !containerRef.value) return
  // displayMode 刚变化但数据尚未加载完成 — 保存当前滚动百分比
  previousScrollPct = containerRef.value.scrollTop /
    (containerRef.value.scrollHeight - containerRef.value.clientHeight || 1)
  // 等数据加载 + DOM 渲染完成后恢复
  nextTick(() => {
    if (containerRef.value) {
      const container = containerRef.value
      const newMaxScroll = container.scrollHeight - container.clientHeight
      container.scrollTop = newMaxScroll * previousScrollPct
    }
  })
})

// 防抖定时器（分开管理，避免互相干扰）
const loadMoreTimer = ref<number | null>(null)
const restoreTimer = ref<number | null>(null)
const contentScrollTimer = ref<number | null>(null)

// 判断用户是否在底部附近（阈值 150px）
const isNearBottom = () => {
  if (!containerRef.value) return true
  const container = containerRef.value
  return container.scrollHeight - container.scrollTop - container.clientHeight < 150
}

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

    if (restoreTimer.value) clearTimeout(restoreTimer.value)
    restoreTimer.value = window.setTimeout(() => {
      isRestoringScroll.value = false
      restoreTimer.value = null
    }, 150)
  })
}

const scrollToBottom = () => {
  if (isRestoringScroll.value) return
  // 用户已上滑查看历史时，不强制滚动
  if (!isNearBottom()) return

  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}

// ====== 明细模式：消息数量变化时自动滚动 ======
watch(
  () => chatStore.filteredMessages.length,
  () => {
    if (isRestoringScroll.value) return
    if (!chatStore.loadingMore && !isConciseMode.value) {
      scrollToBottom()
    }
  }
)

// ====== 明细模式：流式内容更新时自动滚动 ======
watch(
  () => chatStore.filteredMessages.map(m => m.data?.content).join(''),
  () => {
    if (isRestoringScroll.value) return
    if (contentScrollTimer.value) clearTimeout(contentScrollTimer.value)
    contentScrollTimer.value = window.setTimeout(() => {
      if (!isConciseMode.value) {
        scrollToBottom()
      }
    }, 50)
  }
)

// ====== 简洁模式：新 turn 出现或活跃 turn 更新时自动滚动 ======
watch(
  () => chatStore.filteredTurnSummaries.length,
  () => {
    if (isRestoringScroll.value) return
    if (!isConciseMode.value || chatStore.loadingMoreTurns) return
    scrollToBottom()
  }
)

// 简洁模式下 turn 的 finalResponse/reasoningContent 更新时自动滚动
watch(
  () => chatStore.filteredTurnSummaries
    .map(t => `${t.finalResponse}|${t.reasoningContent}|${t.status}`)
    .join('---'),
  () => {
    if (isRestoringScroll.value) return
    if (!isConciseMode.value) return
    if (contentScrollTimer.value) clearTimeout(contentScrollTimer.value)
    contentScrollTimer.value = window.setTimeout(() => {
      scrollToBottom()
    }, 50)
  }
)

const handleScroll = (event: Event) => {
  const target = event.target as HTMLElement

  if (loadMoreTimer.value) clearTimeout(loadMoreTimer.value)

  loadMoreTimer.value = window.setTimeout(() => {
    if (target.scrollTop < 50) {
      if (isConciseMode.value) {
        // 简洁模式：加载更多 turn
        if (!chatStore.loadingMoreTurns && chatStore.hasMoreTurns) {
          const scrollState = saveScrollState()
          chatStore
            .loadTurnHistory(chatStore.sessionId, true, chatStore.executionId)
            .then(() => {
              restoreScrollState(scrollState)
            })
            .catch((error) => {
              console.error('加载历史轮次失败:', error)
              isRestoringScroll.value = false
            })
        }
      } else {
        // 明细模式：加载更多消息（原有逻辑）
        if (!chatStore.loadingMore && chatStore.hasMoreHistory) {
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
      }
    }
  }, 200)
}

onUnmounted(() => {
  if (loadMoreTimer.value) clearTimeout(loadMoreTimer.value)
  if (restoreTimer.value) clearTimeout(restoreTimer.value)
  if (contentScrollTimer.value) clearTimeout(contentScrollTimer.value)
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
    class="flex-1 bg-white rounded-lg border shadow-sm overflow-y-auto p-4"
    :class="{ 'space-y-3': !isConciseMode }"
    @scroll="handleScroll"
  >
    <!-- 简明模式 -->
    <template v-if="isConciseMode">
      <div v-if="chatStore.loadingMoreTurns" class="flex items-center justify-center py-2 text-gray-400 text-sm">
        <span class="mr-2">加载中...</span>
      </div>
      <div
        v-else-if="!chatStore.hasMoreTurns && chatStore.filteredTurnSummaries.length > 0"
        class="flex items-center justify-center py-2 text-gray-400 text-sm"
      >
        <span>没有更多历史轮次了</span>
      </div>

      <div v-if="!chatStore.filteredTurnSummaries.length" class="flex flex-col items-center justify-center h-full text-gray-400">
        <div class="text-4xl mb-2">📊</div>
        <div class="text-sm">暂无轮次数据</div>
      </div>

      <div class="space-y-3">
        <ChatTurnCard
          v-for="(turn, idx) in chatStore.filteredTurnSummaries"
          :key="turn.turnId"
          :turn="turn"
          :consecutive-agent="idx > 0 && turn.agentId === chatStore.filteredTurnSummaries[idx - 1].agentId"
        />
      </div>
    </template>

    <!-- 明细模式 -->
    <template v-else>
      <div v-if="chatStore.loadingMore" class="flex items-center justify-center py-2 text-gray-400 text-sm">
        <span class="mr-2">加载中...</span>
      </div>
      <div
        v-else-if="!chatStore.hasMoreHistory && chatStore.filteredMessages.length > 0"
        class="flex items-center justify-center py-2 text-gray-400 text-sm"
      >
        <span>没有更多历史消息了</span>
      </div>

      <div v-if="!chatStore.filteredMessages.length" class="flex flex-col items-center justify-center h-full text-gray-400">
        <div class="text-4xl mb-2">💬</div>
        <div v-if="chatStore.urlSessionId && !chatStore.connected" class="text-sm">正在自动连接...</div>
        <div v-else-if="chatStore.urlSessionId && chatStore.connected" class="text-sm">已连接，等待消息...</div>
        <div v-else class="text-sm">未设置session_id。请手动输入或通过URL参数传入。</div>
      </div>

      <ChatMessageItem v-for="m in chatStore.filteredMessages" :key="m.message_id" :message="m" />
    </template>

    <!-- 重做按钮 - 撤销成功后显示（两种模式共用） -->
    <div
      v-if="chatStore.showRedoButton && !chatStore.isAgentOrchestration"
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
          <span>Redo</span>
        </span>
      </el-button>
    </div>
  </div>
</template>
