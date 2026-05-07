<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useChatStore } from './stores/chat'
import AgentSidebar from './components/AgentSidebar.vue'
import ChatMessageList from './components/ChatMessageList.vue'
import ChatInput from './components/ChatInput.vue'
import ChatInfoSidebar from './components/ChatInfoSidebar.vue'
import PermissionDialog from './components/PermissionDialog.vue'
import AgentQueryDialog from './components/AgentQueryDialog.vue'
import RunnerStatusBar from './components/RunnerStatusBar.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'
import TaskPage from './components/TaskPage.vue'
import JobPage from './components/JobPage.vue'

const chatStore = useChatStore()

// 页面管理: 'chat' | 'tasks' | 'jobs'
const currentPage = ref('chat')

function navigate(page: string) {
  currentPage.value = page
}

function goBack() {
  currentPage.value = 'chat'
}

onMounted(() => {
  chatStore.init()
})

onUnmounted(() => {
  // cleanup
})
</script>

<template>
  <div class="app-container">
    <!-- Chat View -->
    <div v-if="currentPage === 'chat'" class="chat-container">
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
        <ChatInfoSidebar v-if="chatStore.showRightSidebar" @navigate="navigate" />
      </div>

      <!-- Dialogs -->
      <PermissionDialog />
      <AgentQueryDialog />
    </div>

    <!-- Task Management Page -->
    <div v-else-if="currentPage === 'tasks'" class="sub-page">
      <div class="sub-page-bar">
        <button class="back-btn" @click="goBack">← 返回聊天</button>
      </div>
      <TaskPage :session-id="chatStore.sessionId" />
    </div>

    <!-- Job Management Page -->
    <div v-else-if="currentPage === 'jobs'" class="sub-page">
      <div class="sub-page-bar">
        <button class="back-btn" @click="goBack">← 返回聊天</button>
      </div>
      <JobPage :session-id="chatStore.sessionId" />
    </div>
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

.app-container {
  height: 100%;
  display: flex;
  flex-direction: column;
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
  min-height: 0;
}

/* Sub-page (Task / Job management) */
.sub-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sub-page-bar {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.back-btn {
  background: none;
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.back-btn:hover {
  background: var(--bg-tertiary);
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
