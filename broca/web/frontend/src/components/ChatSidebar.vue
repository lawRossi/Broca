<script setup lang="ts">
import { useChatStore } from '@/stores'

const chatStore = useChatStore()
</script>

<template>
  <div 
    class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      'flex': !chatStore.isMobile || chatStore.showLeftSidebar,
      'hidden': chatStore.isMobile && !chatStore.showLeftSidebar,
      'absolute inset-x-2 top-20 bottom-4 z-40 bg-gray-50 p-3 rounded-lg shadow-xl border': chatStore.isMobile && chatStore.showLeftSidebar
    }"
  >
    <div v-if="chatStore.isMobile && chatStore.showLeftSidebar" class="flex justify-between items-center lg:hidden">
      <span class="text-sm font-semibold text-gray-700">Settings</span>
      <el-button size="small" @click="chatStore.showLeftSidebar = false">✕</el-button>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="text-sm font-semibold text-gray-900 mb-3">Message Filters</div>
      <div class="space-y-2">
        <el-checkbox v-model="chatStore.messageFilters.showUser" size="small">
          <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-blue-500"></span>
            User Messages
          </span>
        </el-checkbox>
        <el-checkbox v-model="chatStore.messageFilters.showAssistant" size="small">
          <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-500"></span>
            Assistant
          </span>
        </el-checkbox>
        <el-checkbox v-model="chatStore.messageFilters.showSystem" size="small">
          <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-gray-500"></span>
            System
          </span>
        </el-checkbox>
        <el-checkbox v-model="chatStore.messageFilters.showError" size="small">
          <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-red-500"></span>
            Errors
          </span>
        </el-checkbox>
      </div>
      
      <div class="mt-4 pt-3 border-t text-xs text-gray-500">
        Showing {{ chatStore.filteredMessages.length }} of {{ chatStore.uiMessages.length }} messages
      </div>
    </div>

    <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
      <div class="text-sm font-semibold text-gray-900 mb-3">Quick Commands</div>
      <div class="space-y-1 text-xs">
        <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="chatStore.input = '/help'">
          <code class="bg-gray-100 px-1 rounded">/help</code>
          <span class="text-gray-600">Show help</span>
        </div>
        <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="chatStore.input = '/clear'">
          <code class="bg-gray-100 px-1 rounded">/clear</code>
          <span class="text-gray-600">Clear chat</span>
        </div>
        <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="chatStore.input = '/status'">
          <code class="bg-gray-100 px-1 rounded">/status</code>
          <span class="text-gray-600">Show status</span>
        </div>
        <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="chatStore.input = '/filter'">
          <code class="bg-gray-100 px-1 rounded">/filter</code>
          <span class="text-gray-600">Toggle filters</span>
        </div>
      </div>
    </div>
  </div>
</template>
