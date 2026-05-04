<script setup lang="ts">
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
</script>

<template>
  <Teleport to="body">
    <div v-if="chatStore.permissionDialog.visible" class="dialog-overlay">
      <div class="dialog-container">
        <div class="dialog-header">
          <span class="dialog-icon">🔒</span>
          <span class="dialog-title">Permission Required</span>
        </div>
        <div class="dialog-body">
          <p>{{ chatStore.permissionDialog.message }}</p>
        </div>
        <div class="dialog-footer">
          <button class="btn btn-secondary" @click="chatStore.respondPermission(false)">
            Deny
          </button>
          <button class="btn btn-primary" @click="chatStore.respondPermission(true)">
            Allow
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog-container {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
  min-width: 300px;
  max-width: 500px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.dialog-icon { font-size: 20px; }

.dialog-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.dialog-body {
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn {
  border: none;
  border-radius: 4px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}

.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
}

.btn-primary:hover {
  background: var(--button-hover-bg);
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-secondary:hover {
  background: var(--border-color);
}
</style>
