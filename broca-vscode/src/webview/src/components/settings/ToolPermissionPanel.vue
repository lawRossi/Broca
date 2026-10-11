<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { postMessage, onMessage } from '../../api/vscode'
import type { ToolPermissionConfig } from '../../types'
import { PERMISSION_VALUES } from '../../types'

import './settings.css'

// --- State ---
const loading = ref(false)
const saving = ref(false)
const config = ref<ToolPermissionConfig>({ tools: {} })
const initialJson = ref('{}')
const damaged = ref(false)
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)
const saveFailed = ref(false)
const autoSaveBlocked = ref(false)
const lastSavedAt = ref<Date | null>(null)
const toast = ref({ visible: false, message: '', type: 'error' as 'error' | 'success' })
let toastTimer: ReturnType<typeof setTimeout> | null = null
let unlisten: (() => void) | null = null
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let saveTimeout: ReturnType<typeof setTimeout> | null = null
let mutatedDuringSave = false

const toolRows = computed<{ name: string; permission: string }[]>(() =>
  Object.entries(config.value.tools || {}).map(([name, permission]) => ({ name, permission }))
)

const DEFAULT_DESCRIPTION =
  '工具权限配置文件。读取顺序（找到第一个即停）：① workspace/.broca/ → ② ~/.broca/configs/ → ③ 全部默认 allow'
const DEFAULT_PERMISSION_DESC: Record<string, string> = {
  allow: '直接执行，无需询问',
  ask: '每次执行前询问用户',
  forbidden: '禁止执行',
}

const descriptionText = computed(() => config.value._description || DEFAULT_DESCRIPTION)
const permissionValueText = (key: string): string => {
  const values = config.value._permission_values
  return (values && values[key]) || DEFAULT_PERMISSION_DESC[key] || key
}

// --- Toast ---
function showToast(msg: string, type: 'error' | 'success', duration = 4000) {
  toast.value = { visible: true, message: msg, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value.visible = false
  }, duration)
}

// --- Add dialog ---
const addDialogVisible = ref(false)
const newToolName = ref('')
const newToolPermission = ref<string>('allow')

function openAddDialog() {
  newToolName.value = ''
  newToolPermission.value = 'allow'
  addDialogVisible.value = true
}

function confirmAddTool() {
  const name = newToolName.value.trim()
  if (!name) {
    showToast('工具名不能为空', 'error')
    return
  }
  if (name in (config.value.tools || {})) {
    showToast(`工具 "${name}" 已存在`, 'error')
    return
  }
  if (!config.value.tools) config.value.tools = {}
  config.value.tools[name] = newToolPermission.value
  addDialogVisible.value = false
  showToast(`已添加工具 "${name}"（保存后生效）`, 'success', 2000)
}

// --- Operations ---
function setPermission(name: string, permission: string) {
  if (!config.value.tools) config.value.tools = {}
  config.value.tools[name] = permission
}

function removeTool(name: string) {
  const tools = { ...(config.value.tools || {}) }
  delete tools[name]
  config.value.tools = tools
  showToast(`已删除工具 "${name}"（保存后生效）`, 'success', 2000)
}

// --- Load ---
let loadTimeout: ReturnType<typeof setTimeout> | null = null

function loadConfig() {
  loading.value = true
  if (loadTimeout) clearTimeout(loadTimeout)
  loadTimeout = setTimeout(() => {
    if (loading.value) {
      loading.value = false
      showToast('加载超时，请检查服务器是否运行', 'error')
    }
  }, 8000)
  postMessage({ type: 'getToolPermissionConfig' })
}

onMounted(() => {
  loadConfig()
  unlisten = onMessage((data: any) => {
    switch (data.type) {
      case 'toolPermission': {
        const { config: cfg, damaged: dmg } = data.payload
        if (loadTimeout) {
          clearTimeout(loadTimeout)
          loadTimeout = null
        }
        loading.value = false
        damaged.value = !!dmg
        if (dmg) {
          config.value = { tools: {} }
          initialJson.value = '{}'
        } else {
          config.value = {
            _description: cfg?._description,
            _permission_values: cfg?._permission_values,
            tools: { ...(cfg?.tools || {}) },
          }
          initialJson.value = JSON.stringify(config.value)
        }
        break
      }
      case 'toolPermissionSaved':
        saving.value = false
        if (saveTimeout) {
          clearTimeout(saveTimeout)
          saveTimeout = null
        }
        saveFailed.value = false
        autoSaveBlocked.value = false
        initialJson.value = JSON.stringify(config.value)
        lastSavedAt.value = new Date()
        showToast('工具权限已保存', 'success', 2000)
        break
      case 'toolPermissionError':
        if (loadTimeout) {
          clearTimeout(loadTimeout)
          loadTimeout = null
        }
        if (saveTimeout) {
          clearTimeout(saveTimeout)
          saveTimeout = null
        }
        loading.value = false
        saving.value = false
        saveFailed.value = true
        showToast(data.payload?.message || '保存失败', 'error')
        break
    }
  })
})

onBeforeUnmount(() => {
  if (unlisten) unlisten()
  if (toastTimer) clearTimeout(toastTimer)
  if (loadTimeout) clearTimeout(loadTimeout)
  if (saveTimeout) clearTimeout(saveTimeout)
  clearAutoSaveTimer()
})

// --- Auto-save ---
const AUTO_SAVE_DELAY = 1200

function clearAutoSaveTimer() {
  if (autoSaveTimer !== null) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
}

function scheduleAutoSave() {
  clearAutoSaveTimer()
  if (loading.value || !dirty.value) return
  autoSaveTimer = setTimeout(() => {
    autoSaveTimer = null
    runAutoSave()
  }, AUTO_SAVE_DELAY)
}

watch(
  config,
  () => {
    if (loading.value) return
    if (saving.value) {
      mutatedDuringSave = true
      return
    }
    scheduleAutoSave()
  },
  { deep: true }
)

// --- Validation ---
function validateBeforeSave(): string | null {
  const tools = config.value.tools || {}
  if (typeof tools !== 'object') return 'tools 必须是对象'
  const names = Object.keys(tools)
  if (names.some((n) => !n.trim())) return '存在空的工具名'
  if (new Set(names).size !== names.length) return '工具名不能重复'
  for (const [name, permission] of Object.entries(tools)) {
    if (!(PERMISSION_VALUES as readonly string[]).includes(String(permission))) {
      return `工具 "${name}" 的权限值必须是 ${PERMISSION_VALUES.join(' / ')} 之一`
    }
  }
  return null
}

function persistConfig() {
  saving.value = true
  saveFailed.value = false
  if (saveTimeout) clearTimeout(saveTimeout)
  // 兜底计时器先于 postMessage 设置：否则序列化异常会导致 saving 永久卡在「保存中…」
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
    postMessage({ type: 'saveToolPermissionConfig', payload: plainConfig })
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
  // Note: initialJson/lastSavedAt updated on toolPermissionSaved message
}

function runAutoSave() {
  if (!dirty.value || saving.value || loading.value) return
  const error = validateBeforeSave()
  if (error) {
    autoSaveBlocked.value = true
    return
  }
  persistConfig()
}

function saveNow() {
  clearAutoSaveTimer()
  const error = validateBeforeSave()
  if (error) {
    showToast(error, 'error')
    return
  }
  persistConfig()
}

function reset() {
  clearAutoSaveTimer()
  autoSaveBlocked.value = false
  saveFailed.value = false
  lastSavedAt.value = null
  loadConfig()
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
    <div v-if="damaged" class="damaged-banner">⚠️ 配置文件缺失或损坏，当前显示空列表。保存将创建新文件。</div>

    <!-- Info block -->
    <section class="section" style="background: var(--bg-primary); border-color: var(--border-color)">
      <p class="field-hint" style="margin-bottom: 4px">{{ descriptionText }}</p>
      <p class="field-hint">
        权限值含义：
        <span v-for="p in PERMISSION_VALUES" :key="p" style="margin-right: 8px">
          <strong>{{ p }}</strong
          >：{{ permissionValueText(p) }}
        </span>
      </p>
    </section>

    <!-- Toolbar -->
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
        flex-wrap: wrap;
        gap: 8px;
      "
    >
      <div style="display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-secondary)">
        <span v-if="loading">加载中…</span>
        <span v-else-if="saving">保存中…</span>
        <span v-else-if="saveFailed" style="color: #e06060">保存失败，请点击「保存」重试</span>
        <span v-else-if="autoSaveBlocked" style="color: #c0a040">修改未通过校验，暂未保存</span>
        <span v-else-if="lastSavedAt && !dirty">已自动保存 {{ lastSavedAt.toLocaleTimeString() }}</span>
        <span v-else-if="dirty">即将自动保存…</span>
      </div>
      <div style="display: flex; gap: 8px">
        <button class="action-button action-button--secondary" @click="openAddDialog">+ 添加工具</button>
        <button class="action-button action-button--secondary" :disabled="saving" @click="reset">重置</button>
        <button class="save-button" :disabled="saving || !dirty" @click="saveNow">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-state">加载配置中…</div>

    <!-- Table -->
    <div v-else>
      <table class="config-table">
        <thead>
          <tr>
            <th>工具名</th>
            <th>权限</th>
            <th style="width: 60px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in toolRows" :key="row.name">
            <td style="font-family: monospace">{{ row.name }}</td>
            <td>
              <select
                :value="row.permission"
                class="cell-input"
                style="width: 180px"
                @change="setPermission(row.name, ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="p in PERMISSION_VALUES" :key="p" :value="p">
                  {{ p }}（{{ permissionValueText(p) }}）
                </option>
              </select>
            </td>
            <td>
              <button class="delete-btn" title="删除" @click="removeTool(row.name)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="toolRows.length === 0" class="empty-state">暂无工具配置，点击「添加工具」创建</div>
    </div>

    <!-- Add dialog -->
    <div v-if="addDialogVisible" class="modal-overlay" @click.self="addDialogVisible = false">
      <div class="modal">
        <div class="modal-title">添加工具</div>
        <div class="field">
          <label class="field-label">工具名</label>
          <input
            v-model="newToolName"
            class="field-input"
            placeholder="如 read_file、bash"
            @keyup.enter="confirmAddTool"
          />
        </div>
        <div class="field">
          <label class="field-label">权限</label>
          <select v-model="newToolPermission" class="field-select">
            <option v-for="p in PERMISSION_VALUES" :key="p" :value="p">{{ p }}（{{ permissionValueText(p) }}）</option>
          </select>
        </div>
        <div class="modal-actions">
          <button class="action-button action-button--secondary" @click="addDialogVisible = false">取消</button>
          <button class="save-button" @click="confirmAddTool">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>
