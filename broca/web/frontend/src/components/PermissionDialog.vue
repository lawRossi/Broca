<script setup lang="ts">
import { useChatStore } from '@/stores'

const chatStore = useChatStore()
</script>

<template>
  <el-dialog 
    v-model="chatStore.permissionDialog.visible" 
    title="Permission Request" 
    :width="chatStore.isMobile ? '90%' : '520px'" 
    :close-on-click-modal="false"
  >
    <div class="flex items-start gap-3">
      <div class="text-3xl">
        🔐
      </div>
      <div class="text-sm text-gray-700 whitespace-pre-wrap flex-1">
        {{ chatStore.permissionDialog.message }}
      </div>
    </div>
    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button @click="chatStore.respondPermission(false)">
          Deny
        </el-button>
        <el-button type="primary" @click="chatStore.respondPermission(true)">
          Allow
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
