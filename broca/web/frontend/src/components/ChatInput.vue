<script setup lang="ts">
import { useChatStore } from '@/stores'

const chatStore = useChatStore()
</script>

<template>
  <div class="bg-white rounded-lg border shadow-sm p-2 sm:p-4">
    <div class="flex gap-2">
      <el-input
        v-model="chatStore.input"
        placeholder="Type message..."
        @keyup.enter="chatStore.sendUserMessage"
        :disabled="!chatStore.connected"
        :size="chatStore.isMobile ? 'default' : 'large'"
        clearable
      />
      <el-button 
        v-if="chatStore.agentStatus === 'running'"
        type="danger" 
        @click="chatStore.sendAbort"
        :size="chatStore.isMobile ? 'default' : 'large'"
        title="Abort current operation"
      >
        <span class="hidden sm:inline">Abort</span>
        <span class="sm:hidden">⏹</span>
      </el-button>
      <el-button 
        type="primary" 
        @click="chatStore.sendUserMessage" 
        :disabled="!chatStore.connected || !chatStore.input.trim()"
        :size="chatStore.isMobile ? 'default' : 'large'"
      >
        <span class="hidden sm:inline">Send</span>
        <span class="sm:hidden">➤</span>
      </el-button>
    </div>
    <div class="mt-2 text-xs text-gray-400 flex justify-between">
      <span class="hidden sm:inline">Press Enter to send</span>
      <span v-if="!chatStore.connected" class="text-red-500">Not connected</span>
    </div>
  </div>
</template>
