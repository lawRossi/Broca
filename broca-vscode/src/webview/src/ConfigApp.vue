<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { postMessage, onMessage } from './api/vscode'
import type { LLMProvider, LLMModel } from './types'

const config = ref({
  serverUrl: 'http://localhost:8000',
  wsUrl: 'http://localhost:8000',
  supabaseUrl: '',
  supabaseKey: '',
  defaultProvider: '',
  defaultModel: '',
})

const providers = ref<LLMProvider[]>([])
const models = ref<LLMModel[]>([])
const loadingProviders = ref(false)
const loadingModels = ref(false)
const saving = ref(false)

onMounted(() => {
  // Request config from extension
  postMessage({ type: 'getConfig' })
  postMessage({ type: 'getProviders' })

  // Listen for responses
  onMessage((data: any) => {
    switch (data.type) {
      case 'config':
        config.value = { ...config.value, ...data.payload }
        break
      case 'providers':
        providers.value = data.payload || []
        break
      case 'models':
        models.value = data.payload || []
        break
      case 'error':
        console.error('Error:', data.payload.message)
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
  postMessage({ type: 'saveConfig', payload: config.value })
  setTimeout(() => { saving.value = false }, 500)
}
</script>

<template>
  <div class="config-container">
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

    <!-- Supabase Configuration -->
    <section class="section">
      <h2 class="section-title">Supabase Configuration</h2>

      <div class="field">
        <label class="field-label">Supabase URL</label>
        <input v-model="config.supabaseUrl" class="field-input" placeholder="https://your-project.supabase.co" />
      </div>

      <div class="field">
        <label class="field-label">Supabase Anon Key</label>
        <input v-model="config.supabaseKey" class="field-input" type="password" placeholder="your-anon-key" />
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

html, body {
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
</style>
