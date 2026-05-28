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
import { postMessage } from './api/vscode'

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
          <!-- Agent orchestration: read-only banner instead of ChatInput -->
          <div v-if="chatStore.isAgentOrchestration" class="orchestration-readonly-bar">
            <div class="orchestration-readonly-content">
              <span class="orchestration-readonly-icon">⚡</span>
              <div class="orchestration-readonly-text">
                <div class="orchestration-readonly-title">Agent 编排会话</div>
                <div class="orchestration-readonly-desc">此会话为只读模式，聊天仅用于查看执行日志</div>
              </div>
              <button class="orchestration-readonly-btn" @click="postMessage({ type: 'openCrewPanel' })">
                查看编排
              </button>
            </div>
          </div>
          <ChatInput v-else />
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

/* Agent orchestration read-only banner */
.orchestration-readonly-bar {
  flex-shrink: 0;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #333);
  background: var(--vscode-editor-background, #1e1e1e);
}

.orchestration-readonly-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.orchestration-readonly-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.orchestration-readonly-text {
  flex: 1;
  min-width: 0;
}

.orchestration-readonly-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--vscode-editor-foreground, #cccccc);
}

.orchestration-readonly-desc {
  font-size: 11px;
  color: var(--vscode-descriptionForeground, #888);
  margin-top: 2px;
}

.orchestration-readonly-btn {
  flex-shrink: 0;
  padding: 6px 14px;
  background: var(--vscode-button-background, #007acc);
  color: var(--vscode-button-foreground, #fff);
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
}

.orchestration-readonly-btn:hover {
  background: var(--vscode-button-hoverBackground, #005a9e);
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
