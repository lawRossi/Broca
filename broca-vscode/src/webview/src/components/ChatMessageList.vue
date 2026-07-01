<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import ChatMessageItem from './ChatMessageItem.vue'
import ChatTurnCard from './ChatTurnCard.vue'

const chatStore = useChatStore()
const containerRef = ref<HTMLElement>()

// 防抖定时器（分开管理，避免互相干扰）
const loadMoreTimer = ref<number | null>(null)
const restoreTimer = ref<number | null>(null)
const contentScrollTimer = ref<number | null>(null)

// 是否正在恢复滚动位置（加载更多历史后）
const isRestoringScroll = ref(false)

// 模式切换时的滚动位置保留
const pendingScrollPercentage = ref<number | null>(null)

// 判断两个 turn 是否来自同一个 agent
function isConsecutiveAgent(turn: any, index: number): boolean {
  if (index === 0) return false
  const prevTurn = chatStore.turnSummaries[index - 1]
  if (!prevTurn) return false
  return prevTurn.agentId === turn.agentId
}

// 判断用户是否在底部附近（阈值 150px）
function isNearBottom(): boolean {
  if (!containerRef.value) return true
  const container = containerRef.value
  return container.scrollHeight - container.scrollTop - container.clientHeight < 150
}

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

    if (restoreTimer.value) clearTimeout(restoreTimer.value)
    restoreTimer.value = window.setTimeout(() => {
      isRestoringScroll.value = false
      restoreTimer.value = null
    }, 150)
  })
}

const scrollToBottomImmediate = () => {
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
}

const scrollToBottom = () => {
  if (isRestoringScroll.value) return
  // 用户已上滑查看历史时，不强制滚动
  if (!isNearBottom()) return

  nextTick(() => {
    scrollToBottomImmediate()
  })
}

// ==================== 自动滚动（明细模式） ====================
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
// 加防抖避免高频 chunk 导致页面抖动
watch(
  () => chatStore.filteredMessages.map(m => m.data?.content).join(''),
  () => {
    if (isRestoringScroll.value) return
    if (contentScrollTimer.value) clearTimeout(contentScrollTimer.value)
    contentScrollTimer.value = window.setTimeout(() => {
      scrollToBottom()
    }, 50)
  }
)

// ==================== 模式切换滚动保持 ====================
watch(
  () => chatStore.displayMode,
  (newMode, oldMode) => {
    if (!oldMode || !containerRef.value) return
    // 记录切换前的滚动百分比
    const container = containerRef.value
    const scrollPct = container.scrollTop / (container.scrollHeight - container.clientHeight)
    pendingScrollPercentage.value = scrollPct

    nextTick(() => {
      if (pendingScrollPercentage.value !== null && containerRef.value) {
        const c = containerRef.value
        c.scrollTop = pendingScrollPercentage.value * (c.scrollHeight - c.clientHeight)
        pendingScrollPercentage.value = null
      }
    })
  }
)

// 简洁模式下，turnSummaries 更新时自动滚动到底部
watch(
  () => chatStore.turnSummaries.length,
  () => {
    if (chatStore.displayMode !== 'concise') return
    if (isRestoringScroll.value) return
    scrollToBottom()
  }
)

  // ==================== 滚动加载更多（明细模式 + 简洁模式上滑刷新） ====================
const handleScroll = () => {
  const container = containerRef.value
  if (!container) return

  if (loadMoreTimer.value) clearTimeout(loadMoreTimer.value)

  loadMoreTimer.value = window.setTimeout(() => {
    // 简洁模式：上滑加载 turn 历史
    if (chatStore.displayMode === 'concise') {
      if (container.scrollTop < 50 && !chatStore.loadingMoreTurns && chatStore.hasMoreTurns) {
        chatStore.loadTurnHistory(chatStore.sessionId, true, chatStore.executionId)
        // 加载后自动恢复到原位置
        isRestoringScroll.value = true
        setTimeout(() => {
          isRestoringScroll.value = false
        }, 500)
      }
      return
    }

    // 明细模式：上滑加载消息历史
    if (container.scrollTop < 50 && !chatStore.loadingMore && chatStore.hasMoreHistory) {
      const scrollState = saveScrollState()
      chatStore.loadMoreHistory()
      // 立即封锁自动滚动，避免在等待历史数据回来的窗口期内
      // 流式内容更新将用户拉到最底部
      isRestoringScroll.value = true

      // Try to restore scroll position after a short delay
      setTimeout(() => {
        restoreScrollState(scrollState)
      }, 300)
    }
  }, 200)
}

// ==================== 生命周期 ====================
onMounted(() => {
  // 首次挂载时，用户从其他页面切回来期望看到最新消息，
  // 此时 scrollTop 为 0，isNearBottom() 检查不通过，
  // 必须用 scrollToBottomImmediate 强制滚动到底部。
  nextTick(() => {
    scrollToBottomImmediate()
  })
})

onUnmounted(() => {
  if (loadMoreTimer.value) clearTimeout(loadMoreTimer.value)
  if (restoreTimer.value) clearTimeout(restoreTimer.value)
  if (contentScrollTimer.value) clearTimeout(contentScrollTimer.value)
})
</script>

<template>
  <div
    ref="containerRef"
    class="message-list"
    @scroll="handleScroll"
  >
    <!-- 简洁模式：Turn 摘要视图 -->
    <template v-if="chatStore.displayMode === 'concise'">
      <!-- Loading more (turn history) -->
      <div v-if="chatStore.loadingMoreTurns" class="load-more-indicator">
        <span>加载中...</span>
      </div>
      <div
        v-else-if="!chatStore.hasMoreTurns && chatStore.turnSummaries.length > 0"
        class="end-of-history-marker"
      >
        <span>没有更多历史轮次了</span>
      </div>

      <!-- Empty state -->
      <div v-if="chatStore.turnSummaries.length === 0 && !chatStore.loading" class="empty-state">
        <div class="empty-icon">📋</div>
        <div v-if="chatStore.sessionId && !chatStore.connected" class="empty-text">正在自动连接...</div>
        <div v-else-if="chatStore.sessionId && chatStore.connected" class="empty-text">暂无轮次数据，请先发送消息</div>
        <div v-else class="empty-text">未设置 session_id。请通过 URL 参数传入。</div>
      </div>

      <!-- Turn cards -->
      <div
        v-for="(turn, index) in chatStore.filteredTurnSummaries"
        :key="turn.turnId"
        class="message-wrapper"
      >
        <ChatTurnCard :turn="turn" :consecutiveAgent="isConsecutiveAgent(turn, index)" />
      </div>

      <!-- Redo button (简洁模式) -->
      <div v-if="chatStore.showRedoButton" class="redo-container">
        <button class="redo-button" @click="chatStore.sendRedo()">
          ↩️ Redo
        </button>
      </div>
    </template>

    <!-- 明细模式：逐条消息视图 -->
    <template v-else>
      <!-- Loading more indicator -->
      <div v-if="chatStore.loadingMore" class="load-more-indicator">
        <span>加载中...</span>
      </div>
      <div
        v-else-if="!chatStore.hasMoreHistory && chatStore.filteredMessages.length > 0"
        class="end-of-history-marker"
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
    </template>
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

.end-of-history-marker {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 0;
  color: var(--text-secondary);
  font-size: 13px;
  opacity: 0.5;
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
