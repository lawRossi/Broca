<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { Connection } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores'
import { sessionApi, type Session } from '@/api/session'
import ChatHeader from '@/components/ChatHeader.vue'
import AgentSidebar from '@/components/AgentSidebar.vue'
import ChatMessageList from '@/components/ChatMessageList.vue'
import ChatInput from '@/components/ChatInput.vue'
import ChatInfoSidebar from '@/components/ChatInfoSidebar.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import PermissionDialog from '@/components/PermissionDialog.vue'
import AgentQueryDialog from '@/components/AgentQueryDialog.vue'
import ChatSearchDialog from '@/components/ChatSearchDialog.vue'

const chatStore = useChatStore()
const route = useRoute()

// 搜索弹框
const searchDialogVisible = ref(false)
const searchDialogRef = ref<InstanceType<typeof ChatSearchDialog>>()

const handleSearch = () => {
  searchDialogVisible.value = true
  nextTick(() => searchDialogRef.value?.open())
}

// 当前会话信息（用于判断分类）
const currentSession = ref<Session | null>(null)
const isAgentOrchestration = computed(() => {
  return currentSession.value?.category === 'agent-orchestration'
})

// 编排执行 ID（从 query 参数 ?execution_id=xxx 读取）
const executionId = computed(() => route.query.execution_id as string | undefined)

// 编排是否执行中：存在任一活跃 turn 即为执行中
// - 实时：socket turn_start/turn_end 事件维护 isActive
// - 刷新/进入页面：loadTurnHistory 从 API 恢复（is_active ?? !ended_at）
const isOrchestrationExecuting = computed(() => {
  return chatStore.turnSummaries.some((t) => t.isActive)
})

// 编排会话输入禁用条件：编排执行中 或 runner 未运行
const showOrchestrationBanner = computed(() => {
  return isAgentOrchestration.value && (isOrchestrationExecuting.value || !chatStore.runnerAlive)
})

// 加载会话信息
const loadSessionInfo = async () => {
  const sessionId = chatStore.sessionId || chatStore.urlSessionId
  if (!sessionId) return
  try {
    currentSession.value = await sessionApi.getSession(sessionId)
    chatStore.isAgentOrchestration = currentSession.value?.category === 'agent-orchestration'
  } catch {
    // 忽略错误，不影响聊天功能
  }
}

watch(
  () => chatStore.urlSessionId,
  (newSessionId) => {
    if (newSessionId && newSessionId !== chatStore.sessionId) {
      chatStore.autoConnectAndSubscribe(executionId.value)
      loadSessionInfo()
    }
  },
  { immediate: true }
)

// 同 session 下切换 execution_id 时重新加载历史
watch(executionId, (newExecId, oldExecId) => {
  if (newExecId && newExecId !== oldExecId && chatStore.sessionId) {
    chatStore.executionId = newExecId as string
    chatStore.loadHistory(chatStore.sessionId, false, newExecId)
    chatStore.loadTurnHistory(chatStore.sessionId, false, newExecId)
  }
})

// 离开页面检测：用户离开页面超过超时时间（1分钟），回来时自动刷新
const LEAVE_TIMEOUT_MS = 60 * 1000 // 1 分钟

let _leaveTimestamp = 0
// 记录页面加载时间，兜底后台打开标签页的场景
const _pageLoadTimestamp = Date.now()

function checkAndReload() {
  const lastHidden = Math.max(_leaveTimestamp, _pageLoadTimestamp)
  const elapsed = Date.now() - lastHidden
  if (elapsed >= LEAVE_TIMEOUT_MS) {
    location.reload()
  }
  _leaveTimestamp = 0
}

function onVisibilityChange() {
  if (document.hidden) {
    _leaveTimestamp = Date.now()
  } else {
    checkAndReload()
  }
}

onMounted(() => {
  chatStore.init()
  chatStore.autoConnectAndSubscribe(executionId.value)
  loadSessionInfo()

  // 标准 visibilitychange 监听
  document.addEventListener('visibilitychange', onVisibilityChange)
  // bfcache 恢复兜底（前进/后退缓存）
  window.addEventListener('pageshow', onPageShow)
  // 如果页面加载时就已经在后台，立即记录时间
  if (document.hidden) {
    _leaveTimestamp = Date.now()
  }
})

function onPageShow() {
  if (document.visibilityState === 'visible') {
    checkAndReload()
  }
}

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('pageshow', onPageShow)
  chatStore.cleanup()
})
</script>

<template>
  <div class="h-[100dvh] bg-gray-50 flex flex-col overflow-hidden">
    <LoadingOverlay :visible="chatStore.loading" />
    <ChatHeader @search="handleSearch" />

    <div class="flex-1 mx-auto max-w-7xl w-full px-2 sm:px-2 py-2 sm:py-2 overflow-hidden">
      <div class="grid grid-cols-10 gap-2 sm:gap-4 h-full relative">
        <AgentSidebar />

        <div
          class="flex flex-col gap-1 sm:gap-2 h-full overflow-hidden"
          :class="{
            'col-span-10 lg:col-span-6': true,
          }"
        >
          <ChatMessageList />
          <!-- 编排会话：执行中或 runner 未运行时显示提示横幅（禁用输入），其余情况启用输入 -->
          <template v-if="showOrchestrationBanner">
            <div
              class="flex items-center justify-center gap-2 py-3 px-4 border-t text-sm"
              :class="
                isOrchestrationExecuting
                  ? 'bg-purple-50 border-purple-100 text-purple-600'
                  : 'bg-amber-50 border-amber-100 text-amber-600'
              "
            >
              <el-icon><Connection /></el-icon>
              <span v-if="isOrchestrationExecuting">Agent 编排执行中，暂无法发送消息</span>
              <span v-else>Runner 未运行，请先启动进程后再发送消息</span>
              <el-button size="small" type="primary" plain @click="$router.push('/crews')"> 返回编排管理 </el-button>
            </div>
          </template>
          <ChatInput v-else />
        </div>

        <ChatInfoSidebar />
      </div>
    </div>

    <PermissionDialog />
    <AgentQueryDialog />
    <ChatSearchDialog
      ref="searchDialogRef"
      v-model:visible="searchDialogVisible"
      @close="searchDialogVisible = false"
    />
  </div>
</template>

<style scoped>
.overflow-y-auto::-webkit-scrollbar {
  width: 8px;
}

.overflow-y-auto::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.overflow-y-auto::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

.overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.rounded-lg {
  transition: all 0.2s ease;
}

.rounded-lg:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

@media (max-width: 1023px) {
  .el-button {
    min-height: 36px;
    min-width: 36px;
  }

  .overflow-y-auto {
    -webkit-overflow-scrolling: touch;
  }

  .el-button,
  .el-checkbox {
    user-select: none;
    -webkit-user-select: none;
  }

  * {
    -webkit-tap-highlight-color: transparent;
  }

  input,
  textarea {
    font-size: 16px;
  }
}

@supports (padding: max(0px)) {
  .h-screen {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
    padding-bottom: max(0px, env(safe-area-inset-bottom));
  }
}
</style>
