<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { postMessage, onMessage } from '../../api/vscode'
import type { LLMProvider, LLMModel } from '../../types'

import './settings.css'

const config = ref({
  serverUrl: 'http://localhost:8000',
  wsUrl: 'http://localhost:8000',
  cloudflareAccountId: '',
  cloudflareAccessKeyId: '',
  cloudflareSecretAccessKey: '',
  cloudflareBucket: '',
  cloudflarePublicUrl: '',
  supabaseUrl: '',
  supabaseS3AccessKeyId: '',
  supabaseS3SecretAccessKey: '',
  defaultProvider: '',
  defaultModel: '',
})

const providers = ref<LLMProvider[]>([])
const models = ref<LLMModel[]>([])
const loadingProviders = ref(false)
const loadingModels = ref(false)
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
  postMessage({ type: 'getProviders' })

  unlisten = onMessage((data: any) => {
    switch (data.type) {
      case 'config':
        config.value = { ...config.value, ...data.payload }
        if (config.value.defaultProvider) {
          const provider = config.value.defaultProvider
          setTimeout(() => {
            postMessage({ type: 'getModels', payload: { provider } })
          }, 100)
        }
        break
      case 'providers':
        providers.value = data.payload || []
        break
      case 'models':
        models.value = data.payload || []
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

function onProviderChange() {
  config.value.defaultModel = ''
  models.value = []
  if (config.value.defaultProvider) {
    postMessage({ type: 'getModels', payload: { provider: config.value.defaultProvider } })
  }
}

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

    <!-- Storage Configuration -->
    <section class="section">
      <h2 class="section-title">Storage Configuration</h2>
      <p class="field-hint">配置 S3 兼容的存储后端用于文件上传。Cloudflare R2 和 Supabase S3 二选一。</p>

      <div class="storage-section">
        <h3 class="subsection-title">Option A: Cloudflare R2（推荐）</h3>
        <div class="field">
          <label class="field-label">Account ID</label>
          <input v-model="config.cloudflareAccountId" class="field-input" placeholder="your-account-id" />
        </div>
        <div class="field">
          <label class="field-label">Access Key ID</label>
          <input v-model="config.cloudflareAccessKeyId" class="field-input" placeholder="your-access-key-id" />
        </div>
        <div class="field">
          <label class="field-label">Secret Access Key</label>
          <input
            v-model="config.cloudflareSecretAccessKey"
            class="field-input"
            type="password"
            placeholder="your-secret-access-key"
          />
        </div>
        <div class="field">
          <label class="field-label">Bucket Name</label>
          <input v-model="config.cloudflareBucket" class="field-input" placeholder="my-bucket" />
        </div>
        <div class="field">
          <label class="field-label">Public URL (可选)</label>
          <input v-model="config.cloudflarePublicUrl" class="field-input" placeholder="https://pub-xxxx.r2.dev" />
          <p class="field-hint">如果不填，将使用默认 R2.dev 域名</p>
        </div>
      </div>

      <div class="storage-divider">
        <span>— 或 —</span>
      </div>

      <div class="storage-section">
        <h3 class="subsection-title">Option B: Supabase S3</h3>
        <div class="field">
          <label class="field-label">Supabase URL</label>
          <input v-model="config.supabaseUrl" class="field-input" placeholder="https://your-project.supabase.co" />
        </div>
        <div class="field">
          <label class="field-label">S3 Access Key ID</label>
          <input v-model="config.supabaseS3AccessKeyId" class="field-input" placeholder="your-s3-access-key" />
        </div>
        <div class="field">
          <label class="field-label">S3 Secret Access Key</label>
          <input
            v-model="config.supabaseS3SecretAccessKey"
            class="field-input"
            type="password"
            placeholder="your-s3-secret-key"
          />
        </div>
      </div>
    </section>

    <!-- Default LLM Configuration -->
    <section class="section">
      <h2 class="section-title">Default LLM Configuration</h2>

      <div class="field">
        <label class="field-label">Default Provider</label>
        <select v-model="config.defaultProvider" class="field-select" @change="onProviderChange">
          <option value="">-- None (use default) --</option>
          <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>

      <div class="field">
        <label class="field-label">Default Model</label>
        <select v-model="config.defaultModel" class="field-select" :disabled="!config.defaultProvider">
          <option value="">-- None (use default) --</option>
          <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>
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
