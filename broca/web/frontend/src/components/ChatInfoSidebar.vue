<script setup lang="ts">
import { useChatStore, DisplayType } from '@/stores'

const chatStore = useChatStore()

const getMessageCount = (displayType: DisplayType) => {
  return chatStore.uiMessages.filter(m => m.displayType === displayType).length
}
</script>

<template>
  <div 
    class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      'flex': !chatStore.isMobile || chatStore.showRightSidebar,
      'hidden': chatStore.isMobile && !chatStore.showRightSidebar,
      'absolute inset-x-2 top-20 bottom-4 z-40 bg-gray-50 p-3 rounded-lg shadow-xl border': chatStore.isMobile && chatStore.showRightSidebar
    }"
  >
    <div v-if="chatStore.isMobile && chatStore.showRightSidebar" class="flex justify-between items-center lg:hidden">
      <span class="text-sm font-semibold text-gray-700">Info</span>
      <el-button size="small" @click="chatStore.showRightSidebar = false">✕</el-button>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="text-sm font-semibold text-gray-900 mb-3">Session Info</div>
      <div class="space-y-3 text-sm">
        <div class="flex justify-between">
          <span class="text-gray-500">Session:</span>
          <span class="font-mono text-xs truncate max-w-[150px]" :title="chatStore.sessionId">
            {{ chatStore.sessionId || '未设置' }}
          </span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-500">Agent:</span>
          <span class="font-mono text-xs">{{ chatStore.agentId }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-500">Status:</span>
          <el-tag :type="chatStore.connected ? 'success' : 'info'" size="small">{{ chatStore.statusText }}</el-tag>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-500">Messages:</span>
          <span class="font-mono">{{ chatStore.uiMessages.length }}</span>
        </div>
      </div>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="text-sm font-semibold text-gray-900 mb-3">Message Statistics</div>
      <div class="space-y-2">
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-blue-500"></span>
            User
          </span>
          <span class="font-mono text-sm">{{ getMessageCount(DisplayType.USER) }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-500"></span>
            Assistant
          </span>
          <span class="font-mono text-sm">{{ getMessageCount(DisplayType.ASSISTANT) }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-gray-500"></span>
            System
          </span>
          <span class="font-mono text-sm">{{ getMessageCount(DisplayType.SYSTEM) }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-red-500"></span>
            Errors
          </span>
          <span class="font-mono text-sm">{{ getMessageCount(DisplayType.ERROR) }}</span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-purple-500"></span>
            Tool Calls
          </span>
          <span class="font-mono text-sm">{{ getMessageCount(DisplayType.TOOL_CALL) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
