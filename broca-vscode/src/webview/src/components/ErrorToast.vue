<script setup lang="ts">
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
</script>

<template>
  <Transition name="toast-fade">
    <div
      v-if="chatStore.errorToast.visible"
      :class="['error-toast', `error-toast--${chatStore.errorToast.type}`]"
      @click="chatStore.hideError()"
    >
      <span class="error-toast__icon">
        <template v-if="chatStore.errorToast.type === 'error'">✕</template>
        <template v-else-if="chatStore.errorToast.type === 'warning'">⚠</template>
        <template v-else>ℹ</template>
      </span>
      <span class="error-toast__message">{{ chatStore.errorToast.message }}</span>
    </div>
  </Transition>
</template>

<style scoped>
.error-toast {
  position: fixed;
  top: 12px;
  right: 12px;
  max-width: 360px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  cursor: pointer;
  z-index: 9999;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  word-break: break-word;
}

.error-toast--error {
  background: #5a1d1d;
  border: 1px solid #c04040;
  color: #f0c0c0;
}

.error-toast--warning {
  background: #5a4a1d;
  border: 1px solid #c0a040;
  color: #f0e0c0;
}

.error-toast--info {
  background: #1d3a5a;
  border: 1px solid #4080c0;
  color: #c0dff0;
}

.error-toast__icon {
  flex-shrink: 0;
  font-size: 14px;
  font-weight: bold;
  line-height: 1.5;
}

.error-toast__message {
  flex: 1;
  min-width: 0;
}

/* Transition */
.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.3s ease;
}

.toast-fade-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.toast-fade-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
