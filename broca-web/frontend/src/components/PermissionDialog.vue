<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '@/stores'

const chatStore = useChatStore()
const isToolPermission = computed(() => chatStore.permissionDialog.requestType === 'tool')
</script>

<template>
  <el-dialog
    v-model="chatStore.permissionDialog.visible"
    :title="isToolPermission ? '工具权限请求' : '权限请求'"
    :width="chatStore.isMobile ? '92%' : '480px'"
    :close-on-click-modal="false"
  >
    <div class="flex items-start gap-3 py-2">
      <div class="text-2xl leading-none mt-0.5">{{ isToolPermission ? '🔧' : '🔐' }}</div>
      <div class="text-sm whitespace-pre-wrap flex-1 leading-relaxed permission-message">
        {{ chatStore.permissionDialog.message }}
      </div>
    </div>
    <template #footer>
      <!-- Tool permission: 4 options in 2x2 grid -->
      <template v-if="isToolPermission">
        <div class="permission-grid">
          <div class="perm-btn" @click="chatStore.respondPermission(false, 'forbid')">
            <span class="btn-label">🔒 当前Session都不允许</span>
            <span class="btn-desc">后续不再询问</span>
          </div>
          <div class="perm-btn" @click="chatStore.respondPermission(false)">
            <span class="btn-label">❌ 单次不允许</span>
            <span class="btn-desc">仅本次拒绝</span>
          </div>
          <div class="perm-btn" @click="chatStore.respondPermission(true)">
            <span class="btn-label">✅ 单次允许</span>
            <span class="btn-desc">仅本次执行</span>
          </div>
          <div class="perm-btn" @click="chatStore.respondPermission(true, 'allow')">
            <span class="btn-label">🔓 当前Session都允许</span>
            <span class="btn-desc">后续不再询问</span>
          </div>
        </div>
      </template>
      <!-- General permission: 2 options (existing flow) -->
      <template v-else>
        <div class="flex justify-end gap-3">
          <el-button @click="chatStore.respondPermission(false)"> Deny </el-button>
          <el-button @click="chatStore.respondPermission(true)"> Allow </el-button>
        </div>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.permission-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  width: 100%;
}

.perm-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: auto;
  min-height: 56px;
  padding: 10px 12px;
  border-radius: 8px;
  white-space: normal;
  line-height: 1.3;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s, border-color 0.15s;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}

.perm-btn:hover {
  background: #ecf5ff;
  border-color: #c6e2ff;
}

.perm-btn:active {
  background: #d9ecff;
}

.perm-btn .btn-label {
  display: block;
  width: 100%;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
}

.perm-btn .btn-desc {
  display: block;
  width: 100%;
  font-size: 11px;
  opacity: 0.6;
  line-height: 1.3;
}

.perm-btn:hover .btn-desc {
  opacity: 0.8;
}

/* ========== 暗色模式 ========== */
@media (prefers-color-scheme: dark) {
  :deep(.el-dialog__title) {
    color: #1a1a2e;
    font-weight: 600;
  }

  .permission-message {
    color: #4a4a6a;
  }

  .perm-btn {
    background: #f0f2f5;
    border-color: #d9dce0;
    color: #333;
  }

  .perm-btn:hover {
    background: #e4e7ed;
    border-color: var(--color-primary-400);
  }

  .perm-btn:active {
    background: #d9dce0;
  }
}
</style>
