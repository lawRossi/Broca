<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
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

const chatStore = useChatStore()
const route = useRoute()

// 当前会话信息（用于判断分类）
const currentSession = ref<Session | null>(null)
const isAgentOrchestration = computed(() => {
  return currentSession.value?.category === 'agent-orchestration'
})

// 编排执行 ID（从 query 参数 ?execution_id=xxx 读取）
const executionId = computed(() => route.query.execution_id as string | undefined)

// 加载会话信息
const loadSessionInfo = async () => {
  const sessionId = chatStore.sessionId || chatStore.urlSessionId
  if (!sessionId) return
  try {
    currentSession.value = await sessionApi.getSession(sessionId)
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
  }
})

onMounted(() => {
  chatStore.init()
  chatStore.autoConnectAndSubscribe(executionId.value)
  loadSessionInfo()
})

onUnmounted(() => {
  chatStore.cleanup()
})
</script>

<template>
  <div class="h-[100dvh] bg-gray-50 flex flex-col overflow-hidden">
    <LoadingOverlay :visible="chatStore.loading" />
    <ChatHeader />

    <div class="flex-1 mx-auto max-w-7xl w-full px-2 sm:px-2 py-2 sm:py-2 overflow-hidden">
      <div class="grid grid-cols-12 gap-2 sm:gap-4 h-full relative">
        <AgentSidebar />

        <div
          class="flex flex-col gap-1 sm:gap-2 h-full overflow-hidden"
          :class="{
            'col-span-12 lg:col-span-6': true,
          }"
        >
          <ChatMessageList />
          <!-- 编排会话只读，隐藏输入框 -->
          <template v-if="isAgentOrchestration">
            <div class="flex items-center justify-center gap-2 py-3 px-4 bg-purple-50 border-t border-purple-100 text-sm text-purple-600">
              <el-icon><Connection /></el-icon>
              <span>此会话为 Agent 编排会话，聊天仅用于查看执行日志</span>
              <el-button size="small" type="primary" plain @click="$router.push('/crews')">
                返回编排管理
              </el-button>
            </div>
          </template>
          <ChatInput v-else />
        </div>

        <ChatInfoSidebar />
      </div>
    </div>

    <PermissionDialog />
    <AgentQueryDialog />
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
