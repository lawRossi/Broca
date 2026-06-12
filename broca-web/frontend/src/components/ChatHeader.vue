<script setup lang="ts">
import { Search } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores'

const chatStore = useChatStore()

const emit = defineEmits<{
  (e: 'search'): void
}>()

const handleConciseToggle = (val: boolean) => {
  chatStore.toggleDisplayMode()
}
</script>

<template>
  <div class="flex-shrink-0 bg-white border-b shadow-sm">
    <div class="mx-auto max-w-7xl px-1 sm:px-4 py-2 sm:py-1">
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 sm:gap-3">
          <div class="font-bold text-lg sm:text-lg text-gray-900">Broca</div>
          <el-tag
            :type="chatStore.connected ? 'success' : chatStore.connecting ? 'warning' : 'info'"
            size="small"
            class="hidden sm:inline"
          >
            {{ chatStore.statusText }}
          </el-tag>
          <div
            class="sm:hidden w-2 h-2 rounded-full"
            :class="{
              'bg-green-500': chatStore.connected,
              'bg-yellow-500': chatStore.connecting,
              'bg-gray-400': !chatStore.connected && !chatStore.connecting,
            }"
          />
        </div>

        <div class="flex items-center gap-2">
          <!-- 简洁/明细模式切换 -->
          <el-switch
            :model-value="chatStore.displayMode === 'concise'"
            active-text="📊"
            inactive-text="📋"
            @change="handleConciseToggle"
            size="small"
          />

          <!-- 搜索按钮 -->
          <el-button
            size="small"
            class="!px-2"
            @click="emit('search')"
          >
            <el-icon><Search /></el-icon>
          </el-button>

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
        </div>
      </div>
    </div>
  </div>
</template>
