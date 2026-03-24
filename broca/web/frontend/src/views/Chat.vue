<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '@/stores'
import ChatHeader from '@/components/ChatHeader.vue'
import AgentSidebar from '@/components/AgentSidebar.vue'
import ChatMessageList from '@/components/ChatMessageList.vue'
import ChatInput from '@/components/ChatInput.vue'
import ChatInfoSidebar from '@/components/ChatInfoSidebar.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import PermissionDialog from '@/components/PermissionDialog.vue'

const chatStore = useChatStore()

watch(() => chatStore.urlSessionId, (newSessionId) => {
  if (newSessionId && newSessionId !== chatStore.sessionId) {
    chatStore.autoConnectAndSubscribe()
  }
}, { immediate: true })

onMounted(() => {
  chatStore.init()
  chatStore.autoConnectAndSubscribe()
})

onUnmounted(() => {
  chatStore.cleanup()
})
</script>

<template>
  <div class="h-screen bg-gray-50 flex flex-col overflow-hidden">
    <LoadingOverlay :visible="chatStore.loading" />
    <ChatHeader />
    
    <div class="flex-1 mx-auto max-w-7xl w-full px-2 sm:px-4 py-2 sm:py-4 overflow-hidden">
      <div class="grid grid-cols-12 gap-2 sm:gap-4 h-full">
        <AgentSidebar />
        
        <div 
          class="flex flex-col gap-2 sm:gap-4 h-full overflow-hidden"
          :class="{
            'col-span-12 lg:col-span-6': true,
            'hidden lg:flex': (chatStore.isMobile && chatStore.showLeftSidebar) || (chatStore.isMobile && chatStore.showRightSidebar)
          }"
        >
          <ChatMessageList />
          <ChatInput />
        </div>
        
        <ChatInfoSidebar />
      </div>
    </div>

    <PermissionDialog />
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
