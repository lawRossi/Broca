<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useChatStore } from './stores/chat'
import ChatMessageList from './components/ChatMessageList.vue'
import ChatInput from './components/ChatInput.vue'
import PermissionDialog from './components/PermissionDialog.vue'
import AgentQueryDialog from './components/AgentQueryDialog.vue'
import RunnerStatusBar from './components/RunnerStatusBar.vue'

const chatStore = useChatStore()

onMounted(() => {
  chatStore.init()
})

onUnmounted(() => {
  // cleanup
})
</script>

<template>
  <div class="chat-container">
    <!-- Runner Status Bar -->
    <RunnerStatusBar />

    <!-- Main Chat Area -->
    <div class="chat-main">
      <ChatMessageList />
    </div>

    <!-- Input Area -->
    <ChatInput />

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

.chat-main {
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
