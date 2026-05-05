<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useChatStore } from './stores/chat'
import AgentSidebar from './components/AgentSidebar.vue'
import ChatMessageList from './components/ChatMessageList.vue'
import ChatInput from './components/ChatInput.vue'
import ChatInfoSidebar from './components/ChatInfoSidebar.vue'
import PermissionDialog from './components/PermissionDialog.vue'
import AgentQueryDialog from './components/AgentQueryDialog.vue'
import RunnerStatusBar from './components/RunnerStatusBar.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'

const chatStore = useChatStore()

onMounted(() => {
  console.log('[App] showLeftSidebar:', chatStore.showLeftSidebar)
  console.log('[App] agentNames:', chatStore.agentNames)
  chatStore.init()
})

onUnmounted(() => {
  // cleanup
})
</script>

<template>
  <div class="chat-container">
    <!-- Loading Overlay -->
    <LoadingOverlay :visible="chatStore.loading" />

    <!-- Runner Status Bar -->
    <RunnerStatusBar />

    <!-- Main Content Area: Three-Column Layout -->
    <div class="chat-body">
      <!-- Left Sidebar: Agents -->
      <AgentSidebar v-if="chatStore.showLeftSidebar" />

      <!-- Center: Messages + Input -->
      <div class="chat-center">
        <div class="chat-messages-area">
          <ChatMessageList />
        </div>
        <ChatInput />
      </div>

      <!-- Right Sidebar: Info -->
      <ChatInfoSidebar v-if="chatStore.showRightSidebar" />
    </div>

    <!-- Dialogs -->
    <PermissionDialog />
    <AgentQueryDialog />
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  height: 100%;
  overflow: hidden;
  font-family: var(--font-family);
  font-size: var(--font-size);
  background-color: var(--bg-primary);
  color: var(--text-primary);
}

#app {
  height: 100%;
}

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.chat-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.chat-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.chat-messages-area {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 8px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--scrollbar-bg);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-hover-bg);
}
</style>
