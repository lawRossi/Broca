<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { postMessage, onMessage } from '../../api/vscode'
import type { GeneralConfig, ExecutionConfig, ASRConfig } from '../../types'
import { LOG_LEVELS } from '../../types'

const DECODING_METHODS = ['modified_beam_search', 'greedy_search'] as const

// --- State ---
const loading = ref(true)
const loaded = ref(false) // becomes true only after initial load completes
const saving = ref(false)
const loadError = ref('')
const config = ref<GeneralConfig>({})
const initialJson = ref('')
// 脏状态：本地内容与初始加载基线不一致（computed，避免渲染期副作用误判）
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)
const damaged = ref(false)
const saveFailed = ref(false)
const lastSavedAt = ref<string | null>(null)
const toast = ref({ visible: false, message: '', type: 'error' as 'error' | 'success' })
let toastTimer: ReturnType<typeof setTimeout> | null = null
let unlisten: (() => void) | null = null
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let loadTimeout: ReturnType<typeof setTimeout> | null = null
let saveTimeout: ReturnType<typeof setTimeout> | null = null

const EXECUTION_FIELDS: { key: keyof ExecutionConfig; label: string; unit: string; min?: number }[] = [
  { key: 'step_max_errors', label: 'Step Max Errors', unit: '次' },
  { key: 'llm_retry_delay', label: 'LLM Retry Delay', unit: '秒' },
  { key: 'tool_call_timeout', label: 'Tool Call Timeout', unit: '秒' },
  { key: 'assign_task_timeout', label: 'Assign Task Timeout', unit: '秒' },
  { key: 'llm_timeout', label: 'LLM Timeout', unit: '秒' },
  { key: 'llm_first_chunk_timeout', label: 'LLM First Chunk Timeout', unit: '秒' },
  { key: 'dead_loop_window', label: 'Dead Loop Window', unit: '次' },
  { key: 'message_queue_size', label: 'Message Queue Size', unit: '条' },
  { key: 'permission_request_timeout', label: 'Permission Request Timeout', unit: '秒' },
  { key: 'agent_query_timeout', label: 'Agent Query Timeout', unit: '秒' },
]

// --- Load ---
function load() {
  loading.value = true
  loaded.value = false
  loadError.value = ''
  damaged.value = false
  if (loadTimeout) clearTimeout(loadTimeout)
  loadTimeout = setTimeout(() => {
    if (loading.value) {
      loading.value = false
      loaded.value = true
      loadError.value = '加载超时，请检查服务器是否运行'
    }
  }, 8000)
  postMessage({ type: 'getGeneralConfig' })
}

onMounted(() => {
  load()
  unlisten = onMessage((data: any) => {
    switch (data.type) {
      case 'generalConfig': {
        const { config: cfg, damaged: dmg } = data.payload
        if (loadTimeout) {
          clearTimeout(loadTimeout)
          loadTimeout = null
        }
        loading.value = false
        loaded.value = true
        loadError.value = ''
        damaged.value = !!dmg
        saving.value = false
        config.value = JSON.parse(JSON.stringify(cfg || {}))
        initialJson.value = JSON.stringify(config.value)
        break
      }
      case 'generalConfigSaved':
        saving.value = false
        saveFailed.value = false
        if (saveTimeout) {
          clearTimeout(saveTimeout)
          saveTimeout = null
        }
        initialJson.value = JSON.stringify(config.value)
        lastSavedAt.value = new Date().toLocaleTimeString()
        showToast('Saved', 'success', 2000)
        break
      case 'generalConfigError':
        if (loadTimeout) {
          clearTimeout(loadTimeout)
          loadTimeout = null
        }
        if (saveTimeout) {
          clearTimeout(saveTimeout)
          saveTimeout = null
        }
        const wasLoaded = loaded.value
        loading.value = false
        loaded.value = true
        saving.value = false
        saveFailed.value = true
        if (!wasLoaded && initialJson.value === '') {
          loadError.value = data.payload?.message || '加载失败'
        }
        showToast(data.payload?.message || '保存失败', 'error')
        break
    }
  })
})

onBeforeUnmount(() => {
  if (unlisten) unlisten()
  if (toastTimer) clearTimeout(toastTimer)
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (loadTimeout) clearTimeout(loadTimeout)
  if (saveTimeout) clearTimeout(saveTimeout)
})

// --- Toast ---
function showToast(msg: string, type: 'error' | 'success', duration = 4000) {
  toast.value = { visible: true, message: msg, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value.visible = false
  }, duration)
}

// --- Dirty tracking + auto-save ---
watch(
  config,
  () => {
    if (!dirty.value) return
    if (!loaded.value) return
    if (saving.value || loading.value) return
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      autoSaveTimer = null
      if (!dirty.value || saving.value) return
      saveNow()
    }, 1200)
  },
  { deep: true }
)

// --- Validation ---
function validateBeforeSave(): string | null {
  const exec = config.value.execution
  if (exec) {
    for (const f of EXECUTION_FIELDS) {
      const v = exec[f.key]
      if (v !== undefined && v !== null && (isNaN(v as number) || (v as number) < 0)) {
        return `execution.${f.key} 必须为非负数字`
      }
    }
  }
  const asr = config.value.asr
  if (asr) {
    if (asr.noise_gate_rms !== undefined && isNaN(asr.noise_gate_rms as number)) {
      return 'asr.noise_gate_rms 必须为数字'
    }
  }
  return null
}

// --- Save ---
function saveNow() {
  if (saving.value || !loaded.value) return
  const err = validateBeforeSave()
  if (err) {
    showToast(err, 'error')
    return
  }
  saving.value = true
  saveFailed.value = false
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
  if (saveTimeout) clearTimeout(saveTimeout)
  // 兜底计时器必须先于 postMessage 设置：否则序列化异常会导致 saving 永久卡在「保存中…」
  saveTimeout = setTimeout(() => {
    saveTimeout = null
    if (saving.value) {
      saving.value = false
      saveFailed.value = true
      showToast('保存超时，请重试', 'error')
    }
  }, 10000)
  try {
    // 深度序列化为纯 JSON，避免 payload 内含 Vue 响应式 Proxy 导致 postMessage 序列化抛错
    const plainConfig = JSON.parse(JSON.stringify(config.value))
    postMessage({ type: 'saveGeneralConfig', payload: plainConfig })
  } catch (e: any) {
    if (saveTimeout) {
      clearTimeout(saveTimeout)
      saveTimeout = null
    }
    saving.value = false
    saveFailed.value = true
    const msg = typeof e?.message === 'string' ? e.message : String(e)
    showToast(`保存失败：${msg || '无法发送保存请求'}`, 'error')
  }
}

function reset() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (saveTimeout) clearTimeout(saveTimeout)
  load()
}

// --- Execution / ASR field helpers ---
// 只读读取：绝不在渲染期修改 config，避免凭空注入空分组导致误判为「有未保存修改」
function execValue(key: keyof ExecutionConfig): number | undefined {
  const exec = config.value.execution
  return exec && typeof exec === 'object' ? exec[key] : undefined
}

function asrValue(key: keyof ASRConfig): string | number | undefined {
  const asr = config.value.asr
  return asr && typeof asr === 'object' ? asr[key] : undefined
}

// 写回采用 copy-on-write：仅在真正修改时创建分组并整体替换 config
function setExecField(key: keyof ExecutionConfig, raw: string) {
  const current = config.value.execution
  const exec: ExecutionConfig = current ? { ...current } : {}
  if (raw === '') {
    delete exec[key]
  } else {
    const n = Number(raw)
    if (!isNaN(n)) exec[key] = n
  }
  config.value = { ...config.value, execution: exec }
}

function setAsrField(key: keyof ASRConfig, raw: string) {
  const current = config.value.asr
  const asr: ASRConfig = current ? { ...current } : {}
  if (key === 'noise_gate_rms') {
    if (raw === '') {
      delete asr.noise_gate_rms
    } else {
      const n = Number(raw)
      if (!isNaN(n)) asr.noise_gate_rms = n
    }
  } else {
    if (raw === '') {
      delete asr[key]
    } else {
      asr[key] = raw as any
    }
  }
  config.value = { ...config.value, asr }
}
</script>

<template>
  <div>
    <!-- Toast -->
    <Transition name="toast-fade">
      <div
        v-if="toast.visible"
        :class="['settings-toast', toast.type === 'error' ? 'settings-toast--error' : 'settings-toast--success']"
        @click="toast.visible = false"
      >
        <span class="toast-icon">{{ toast.type === 'error' ? '✕' : '✓' }}</span>
        <span class="toast-message">{{ toast.message }}</span>
      </div>
    </Transition>

    <!-- Damaged banner -->
    <div v-if="damaged" class="damaged-banner">⚠️ 配置文件缺失或损坏，当前显示空配置。编辑后保存将创建/修复文件。</div>

    <!-- Status -->
    <div class="status-bar">
      <span v-if="loading">加载中…</span>
      <span v-else>
        <span
          :class="['status-dot', saving ? 'status-dot--saving' : dirty ? 'status-dot--dirty' : 'status-dot--clean']"
        ></span>
        {{ saving ? '保存中…' : dirty ? '有未保存修改' : '已同步' }}
        <template v-if="lastSavedAt"> · 上次保存 {{ lastSavedAt }}</template>
      </span>
    </div>

    <div v-if="loading" class="empty-state" style="padding: 40px; font-size: 15px; color: var(--text-primary)">
      ⏳ 正在加载配置…
    </div>

    <div
      v-else-if="loadError"
      class="empty-state"
      style="padding: 40px; font-size: 14px; color: var(--error-fg, #e06060); text-align: center"
    >
      <p style="font-size: 28px; margin-bottom: 8px">⚠️</p>
      <p>{{ loadError }}</p>
      <button class="action-button action-button--secondary" style="margin-top: 12px" @click="load">重试</button>
    </div>

    <template v-else>
      <!-- Basic fields -->
      <section class="section">
        <h2 class="section-title">基础配置</h2>
        <div class="field">
          <label class="field-label">Database Directory</label>
          <input v-model="config.database_dir" class="field-input" placeholder="~/.broca/data" />
        </div>
        <div class="field">
          <label class="field-label">Log File</label>
          <input v-model="config.log_file" class="field-input" placeholder="~/.broca/logs/broca.log" />
        </div>
        <div class="field">
          <label class="field-label">Log Level</label>
          <select v-model="config.log_level" class="field-select">
            <option value="">-- 默认 --</option>
            <option v-for="lv in LOG_LEVELS" :key="lv" :value="lv">{{ lv }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">LLM Config File</label>
          <input v-model="config.llm_config_file" class="field-input" placeholder="~/.broca/configs/llm_config.json" />
        </div>
        <div class="field">
          <label class="field-label">Socket Server URL</label>
          <input v-model="config.socket_server_url" class="field-input" placeholder="ws://localhost:9000" />
        </div>
        <div class="field">
          <label class="field-label">API Server URL</label>
          <input v-model="config.api_server_url" class="field-input" placeholder="http://localhost:9000" />
        </div>
      </section>

      <!-- Execution -->
      <section class="section">
        <h2 class="section-title">执行引擎配置</h2>
        <div v-for="f in EXECUTION_FIELDS" :key="f.key" class="field">
          <label class="field-label">{{ f.label }} ({{ f.unit }})</label>
          <input
            type="number"
            class="field-input"
            :min="f.min ?? 0"
            :value="execValue(f.key) ?? ''"
            @change="setExecField(f.key, ($event.target as HTMLInputElement).value)"
          />
        </div>
      </section>

      <!-- ASR -->
      <section class="section">
        <h2 class="section-title">ASR 语音识别</h2>
        <div class="field">
          <label class="field-label">Model Name</label>
          <input
            :value="(asrValue('model_name') as string | undefined) ?? ''"
            class="field-input"
            placeholder="sherpa-onnx-streaming-zipformer-small-bilingual-zh-en"
            @input="setAsrField('model_name', ($event.target as HTMLInputElement).value)"
          />
        </div>
        <div class="field">
          <label class="field-label">Decoding Method</label>
          <select
            :value="(asrValue('decoding_method') as string | undefined) ?? ''"
            class="field-select"
            @change="setAsrField('decoding_method', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">-- 默认 --</option>
            <option v-for="dm in DECODING_METHODS" :key="dm" :value="dm">{{ dm }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">Noise Gate RMS (0 禁用)</label>
          <input
            type="number"
            class="field-input"
            :value="asrValue('noise_gate_rms') ?? ''"
            @change="setAsrField('noise_gate_rms', ($event.target as HTMLInputElement).value)"
          />
        </div>
      </section>

      <!-- Actions -->
      <div class="save-area">
        <button class="action-button action-button--secondary" @click="reset">重置</button>
        <button class="save-button" :disabled="saving" @click="saveNow">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </template>
  </div>
</template>
