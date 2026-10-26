<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { postMessage, onMessage } from '../../api/vscode'

import './settings.css'

const config = ref({
  serverUrl: 'http://localhost:8000',
  wsUrl: 'http://localhost:8000',
})

const saving = ref(false)

// Error toast
const errorToast = ref({ visible: false, message: '' })
let errorToastTimer: ReturnType<typeof setTimeout> | null = null
let unlisten: (() => void) | null = null

function showError(message: string, duration = 5000) {
  errorToast.value = { visible: true, message }
  if (errorToastTimer) clearTimeout(errorToastTimer)
  errorToastTimer = setTimeout(() => {
    errorToast.value.visible = false
  }, duration)
}

function hideError() {
  errorToast.value.visible = false
  if (errorToastTimer) {
    clearTimeout(errorToastTimer)
    errorToastTimer = null
  }
}

onMounted(() => {
  postMessage({ type: 'getConfig' })

  unlisten = onMessage((data: any) => {
    switch (data.type) {
      case 'config':
        config.value = { ...config.value, ...data.payload }
        break
      case 'saved':
        saving.value = false
        break
      case 'error':
        console.error('Error:', data.payload?.message)
        showError(data.payload?.message || '操作失败')
        break
    }
  })
})

onBeforeUnmount(() => {
  if (unlisten) unlisten()
  if (errorToastTimer) clearTimeout(errorToastTimer)
})

function saveConfig() {
  saving.value = true
  try {
    postMessage({ type: 'saveConfig', payload: { ...config.value } })
  } catch (e) {
    console.error('[ClientConfig] Failed to post saveConfig:', e)
  }
  setTimeout(() => {
    if (saving.value) {
      saving.value = false
    }
  }, 2000)
}
</script>

<template>
  <div>
    <!-- Error Toast -->
    <Transition name="toast-fade">
      <div v-if="errorToast.visible" class="settings-toast settings-toast--error" @click="hideError">
        <span class="toast-icon">✕</span>
        <span class="toast-message">{{ errorToast.message }}</span>
      </div>
    </Transition>

    <!-- Server Configuration -->
    <section class="section">
      <h2 class="section-title">Server Configuration</h2>

      <div class="field">
        <label class="field-label">API Server URL</label>
        <input v-model="config.serverUrl" class="field-input" placeholder="http://localhost:8000" />
      </div>

      <div class="field">
        <label class="field-label">WebSocket Server URL</label>
        <input v-model="config.wsUrl" class="field-input" placeholder="http://localhost:8000" />
      </div>
    </section>

    <!-- Save Button -->
    <div class="save-area">
      <button class="save-button" :disabled="saving" @click="saveConfig">
        {{ saving ? 'Saving...' : 'Save Settings' }}
      </button>
    </div>
  </div>
</template>
