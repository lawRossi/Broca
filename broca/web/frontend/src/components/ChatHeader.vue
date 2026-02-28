<script setup lang="ts">
import { useChatStore } from '@/stores'

const chatStore = useChatStore()
</script>

<template>
  <div class="flex-shrink-0 bg-white border-b shadow-sm">
    <div class="mx-auto max-w-7xl px-3 sm:px-4 py-2 sm:py-3">
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 sm:gap-3">
          <div class="font-bold text-lg sm:text-xl text-gray-900">Broca</div>
          <el-tag :type="chatStore.connected ? 'success' : chatStore.connecting ? 'warning' : 'info'" size="small" class="hidden sm:inline">
            {{ chatStore.statusText }}
          </el-tag>
          <div class="sm:hidden w-2 h-2 rounded-full" :class="{
            'bg-green-500': chatStore.connected,
            'bg-yellow-500': chatStore.connecting,
            'bg-gray-400': !chatStore.connected && !chatStore.connecting
          }"></div>
        </div>

        <div class="flex items-center gap-2 sm:gap-4 flex-1 justify-center">
          <div class="flex items-center gap-1.5 sm:gap-2">
            <div class="w-2 h-2 rounded-full flex-shrink-0" :class="{
              'bg-green-500': chatStore.agentStatus === 'idle',
              'bg-yellow-500 animate-pulse': chatStore.agentStatus === 'running',
              'bg-blue-500 animate-pulse': chatStore.agentStatus === 'connecting',
              'bg-gray-400': chatStore.agentStatus === 'disconnected'
            }"></div>
            <span class="text-xs sm:text-sm font-medium truncate max-w-[100px] sm:max-w-none" :class="{
              'text-green-700': chatStore.agentStatus === 'idle',
              'text-yellow-700': chatStore.agentStatus === 'running',
              'text-blue-700': chatStore.agentStatus === 'connecting',
              'text-gray-500': chatStore.agentStatus === 'disconnected'
            }">{{ chatStore.agentStatusText }}</span>
          </div>
          <div v-if="chatStore.agentId && chatStore.agentStatus !== 'disconnected'" class="hidden md:block text-xs text-gray-500">
            Agent: {{ chatStore.agentId }}
          </div>
        </div>

        <div class="flex items-center gap-2">
          <div class="lg:hidden flex items-center gap-1">
            <el-button 
              :type="chatStore.showLeftSidebar ? 'primary' : 'default'"
              size="small"
              class="!px-2"
              @click="chatStore.toggleLeftSidebar"
            >
              <span class="text-xs">⚙️</span>
            </el-button>
            <el-button 
              :type="chatStore.showRightSidebar ? 'primary' : 'default'"
              size="small"
              class="!px-2"
              @click="chatStore.toggleRightSidebar"
            >
              <span class="text-xs">📊</span>
            </el-button>
          </div>
          <div class="hidden sm:block text-xs text-gray-500">
            client: {{ chatStore.socketConfig.clientId.slice(0, 8) }}...
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
