<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
const isToolPermission = computed(() => chatStore.permissionDialog.requestType === 'tool')
</script>

<template>
  <Teleport to="body">
    <div v-if="chatStore.permissionDialog.visible" class="dialog-overlay">
      <div class="dialog-container">
        <div class="dialog-header">
          <span class="dialog-icon">{{ isToolPermission ? '🔧' : '🔒' }}</span>
          <span class="dialog-title">{{ isToolPermission ? 'Tool Permission' : 'Permission Required' }}</span>
        </div>
        <div class="dialog-body">
          <p>{{ chatStore.permissionDialog.message }}</p>
        </div>
        <div class="dialog-footer">
          <!-- Tool permission: 4 options in 2x2 grid -->
          <template v-if="isToolPermission">
            <div class="perm-grid">
              <button class="perm-btn" @click="chatStore.respondPermission(false, 'forbid')">
                <span class="perm-btn-label">🔒 Always Deny</span>
                <span class="perm-btn-desc">for this session</span>
              </button>
              <button class="perm-btn" @click="chatStore.respondPermission(false)">
                <span class="perm-btn-label">❌ Deny Once</span>
                <span class="perm-btn-desc">this time only</span>
              </button>
              <button class="perm-btn" @click="chatStore.respondPermission(true)">
                <span class="perm-btn-label">✅ Allow Once</span>
                <span class="perm-btn-desc">this time only</span>
              </button>
              <button class="perm-btn" @click="chatStore.respondPermission(true, 'allow')">
                <span class="perm-btn-label">🔓 Always Allow</span>
                <span class="perm-btn-desc">for this session</span>
              </button>
            </div>
          </template>
          <!-- General permission: 2 options -->
          <template v-else>
            <button class="btn btn-secondary" @click="chatStore.respondPermission(false)">
              Deny
            </button>
            <button class="btn btn-primary" @click="chatStore.respondPermission(true)">
              Allow
            </button>
          </template>
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
  min-width: 340px;
  max-width: 440px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.dialog-icon { font-size: 18px; }

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
  width: 100%;
}

/* ── 2x2 Grid for tool permission ── */
.perm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.perm-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 10px 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  line-height: 1.3;
  transition: background 0.15s, border-color 0.15s;
}

.perm-btn:hover {
  background: var(--border-color);
  border-color: var(--button-bg);
}

.perm-btn:active {
  background: var(--button-bg);
  color: var(--button-text);
}

/* ── 2-button layout (existing flow) ── */
.btn {
  border: none;
  border-radius: 4px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-secondary:hover {
  background: var(--border-color);
}

.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
}

.btn-primary:hover {
  background: var(--button-hover-bg);
}

.perm-btn-label {
  display: block;
  width: 100%;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.perm-btn-desc {
  display: block;
  width: 100%;
  font-size: 10px;
  opacity: 0.55;
  line-height: 1.3;
}

/* ── 2-button layout (existing flow) ── */
.btn {
  border: none;
  border-radius: 4px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  font-weight: 500;
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
