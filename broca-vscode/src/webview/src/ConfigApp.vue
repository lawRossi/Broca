<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { postMessage, onMessage } from './api/vscode'
import type { LLMProvider, LLMModel } from './types'

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
  // Request config from extension
  postMessage({ type: 'getConfig' })
  postMessage({ type: 'getProviders' })

  // Listen for responses
  onMessage((data: any) => {
    console.log('[Config] Received message:', data.type, data)
    switch (data.type) {
      case 'config':
        config.value = { ...config.value, ...data.payload }
        // 如果已配置默认 provider，自动拉取其模型列表
        if (config.value.defaultProvider) {
          const provider = config.value.defaultProvider
          // 使用 nextTick 确保 providers 列表已渲染后再获取 models
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
        console.error('Error:', data.payload.message)
        showError(data.payload.message || '操作失败')
        break
    }
  })
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
  console.log('[Config] Saving config:', JSON.stringify(config.value))
  try {
    postMessage({ type: 'saveConfig', payload: { ...config.value } })
    console.log('[Config] saveConfig message posted')
  } catch (e) {
    console.error('[Config] Failed to post saveConfig message:', e)
  }
  setTimeout(() => {
    if (saving.value) {
      console.log('[Config] Save timeout - forcing saving=false')
      saving.value = false
    }
  }, 2000)
}
</script>

<template>
  <div class="config-container">
    <!-- Error Toast -->
    <Transition name="toast-fade">
      <div v-if="errorToast.visible" class="config-error-toast" @click="hideError">
        <span class="config-error-toast__icon">✕</span>
        <span class="config-error-toast__message">{{ errorToast.message }}</span>
      </div>
    </Transition>

    <h1 class="title">Broca Settings</h1>

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

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body {
  height: 100%;
  font-family: var(--font-family);
  font-size: var(--font-size);
  background-color: var(--bg-primary);
  color: var(--text-primary);
}

#app {
  height: 100%;
}

.config-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 24px 16px;
}

.title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 24px;
  color: var(--text-primary);
}

.section {
  margin-bottom: 24px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary);
}

.field {
  margin-bottom: 12px;
}

.field:last-child {
  margin-bottom: 0;
}

.field-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.field-input,
.field-select {
  width: 100%;
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 8px 10px;
  font-family: var(--font-family);
  font-size: 13px;
  outline: none;
}

.field-input:focus,
.field-select:focus {
  border-color: var(--focus-border);
}

.field-input::placeholder {
  color: var(--text-secondary);
}

.field-hint {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
  margin-bottom: 8px;
}

.subsection-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary);
}

.storage-section {
  padding: 8px 0;
}

.storage-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 12px 0;
  color: var(--text-secondary);
  font-size: 12px;
  gap: 12px;
}

.storage-divider::before,
.storage-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-color);
}

.field-select {
  cursor: pointer;
}

.field-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.save-area {
  display: flex;
  justify-content: flex-end;
}

.save-button {
  background: var(--button-bg);
  color: var(--button-text);
  border: none;
  border-radius: 4px;
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.save-button:hover {
  background: var(--button-hover-bg);
}

.save-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Error Toast */
.config-error-toast {
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
  background: #5a1d1d;
  border: 1px solid #c04040;
  color: #f0c0c0;
}

.config-error-toast__icon {
  flex-shrink: 0;
  font-size: 14px;
  font-weight: bold;
  line-height: 1.5;
}

.config-error-toast__message {
  flex: 1;
  min-width: 0;
}

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
