<script setup lang="ts">
defineProps<{
  visible: boolean
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="loading-overlay">
      <div class="loading-spinner">
        <div class="spinner"></div>
        <span class="loading-text">Loading...</span>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}

.loading-spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px 32px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color);
  border-top-color: var(--button-bg);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-text {
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
