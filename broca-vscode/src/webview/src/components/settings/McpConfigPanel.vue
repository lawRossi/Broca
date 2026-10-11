<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { postMessage, onMessage } from '../../api/vscode'
import type { McpConfig, McpServerConfig, McpTransport } from '../../types'
import { MCP_TRANSPORTS } from '../../types'

import './settings.css'

// --- State ---
const loading = ref(false)
const saving = ref(false)
const config = ref<McpConfig>({})
const initialJson = ref('{}')
const damaged = ref(false)
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)
const serverCount = computed(() => Object.keys(config.value).length)
const saveFailed = ref(false)
const autoSaveBlocked = ref(false)
const lastSavedAt = ref<Date | null>(null)
const toast = ref({ visible: false, message: '', type: 'error' as 'error' | 'success' })
let toastTimer: ReturnType<typeof setTimeout> | null = null
let unlisten: (() => void) | null = null
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let saveTimeout: ReturnType<typeof setTimeout> | null = null
let mutatedDuringSave = false

// Draft state (blur-to-commit for JSON/multiline fields)
const inputDrafts = ref<Record<string, string>>({})
const jsonEditErrors = ref<Record<string, boolean>>({})
const expandedServers = ref<string[]>([])

const fieldKey = (serverName: string, field: string) => `${serverName}::${field}`
const getDraft = (key: string, fallback: string): string => inputDrafts.value[key] ?? fallback
const setDraft = (key: string, val: string | number) => {
  inputDrafts.value[key] = String(val)
}
const clearDraft = (key: string) => {
  delete inputDrafts.value[key]
}
const setJsonError = (key: string) => {
  jsonEditErrors.value[key] = true
}
const clearJsonError = (key: string) => {
  delete jsonEditErrors.value[key]
}
const hasJsonError = (key: string): boolean => Boolean(jsonEditErrors.value[key])

// --- Transport helpers ---
const transportOf = (server: McpServerConfig): McpTransport => (server.url && !server.command ? 'http' : 'stdio')
const transportLabel: Record<McpTransport, string> = { stdio: 'stdio', http: 'HTTP' }

function setTransport(server: McpServerConfig, transport: McpTransport) {
  if (transport === 'stdio') {
    delete server.url
    delete server.headers
    if (!server.command) server.command = ''
  } else {
    delete server.command
    delete server.args
    delete server.env
    delete server.cwd
    if (!server.url) server.url = ''
  }
}

// --- Field conversion ---
const argsText = (server: McpServerConfig): string => (server.args || []).join('\n')

function applyArgs(serverName: string, server: McpServerConfig, text: string) {
  const args = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
  if (args.length > 0) server.args = args
  else delete server.args
  clearDraft(fieldKey(serverName, 'args'))
}

const stringMapText = (value: Record<string, string> | undefined): string => JSON.stringify(value ?? {}, null, 2)

function parseStringMapText(text: string, label: string): Record<string, string> | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(text || '{}')
  } catch {
    showToast(`${label}不是合法 JSON`, 'error')
    return null
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    showToast(`${label}必须是 JSON 对象`, 'error')
    return null
  }
  const map: Record<string, string> = {}
  for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
    if (typeof v !== 'string') {
      showToast(`${label}的值必须都是字符串`, 'error')
      return null
    }
    map[k] = v
  }
  return map
}

function applyStringMap(serverName: string, server: McpServerConfig, field: 'env' | 'headers', text: string) {
  const key = fieldKey(serverName, field)
  const label = field === 'env' ? '环境变量' : '请求头'
  const map = parseStringMapText(text, label)
  if (map === null) {
    setJsonError(key)
    return
  }
  if (Object.keys(map).length > 0) server[field] = map
  else delete server[field]
  clearJsonError(key)
  clearDraft(key)
}

function setToolTimeout(server: McpServerConfig, value: number | undefined | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    delete server.tool_timeout
  } else {
    server.tool_timeout = Number(value)
  }
}

// --- Rename ---
function renameServer(oldName: string, newNameRaw: string | number) {
  const newName = String(newNameRaw).trim()
  if (!newName || newName === oldName) {
    clearDraft(fieldKey(oldName, 'name'))
    config.value = { ...config.value }
    return
  }
  if (newName in config.value) {
    showToast(`服务器 "${newName}" 已存在`, 'error')
    config.value = { ...config.value }
    clearDraft(fieldKey(oldName, 'name'))
    return
  }
  const rebuilt: McpConfig = {}
  for (const [k, v] of Object.entries(config.value)) {
    rebuilt[k === oldName ? newName : k] = v
  }
  config.value = rebuilt
  expandedServers.value = expandedServers.value.map((n) => (n === oldName ? newName : n))
  clearDraft(fieldKey(oldName, 'name'))
}

// --- Add/Remove ---
const addDialogVisible = ref(false)
const newServerName = ref('')
const newServerTransport = ref<McpTransport>('stdio')
const newServerCommand = ref('')
const newServerArgs = ref('')
const newServerEnv = ref('')
const newServerUrl = ref('')
const newServerHeaders = ref('')
const newServerToolTimeout = ref<string>('')

function openAddDialog() {
  newServerName.value = ''
  newServerTransport.value = 'stdio'
  newServerCommand.value = ''
  newServerArgs.value = ''
  newServerEnv.value = ''
  newServerUrl.value = ''
  newServerHeaders.value = ''
  newServerToolTimeout.value = ''
  addDialogVisible.value = true
}

function confirmAddServer() {
  const name = newServerName.value.trim()
  if (!name) return showToast('服务器名不能为空', 'error')
  if (name in config.value) return showToast(`服务器 "${name}" 已存在`, 'error')
  if (newServerTransport.value === 'stdio' && !newServerCommand.value.trim())
    return showToast('stdio 传输需要填写 command', 'error')
  if (newServerTransport.value === 'http' && !newServerUrl.value.trim())
    return showToast('HTTP 传输需要填写 url', 'error')

  const server: McpServerConfig = {}
  if (newServerTransport.value === 'stdio') {
    server.command = newServerCommand.value.trim()
    const args = newServerArgs.value
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
    if (args.length > 0) server.args = args
    if (newServerEnv.value.trim()) {
      const env = parseStringMapText(newServerEnv.value, '环境变量')
      if (env === null) return
      if (Object.keys(env).length > 0) server.env = env
    }
  } else {
    server.url = newServerUrl.value.trim()
    if (newServerHeaders.value.trim()) {
      const headers = parseStringMapText(newServerHeaders.value, '请求头')
      if (headers === null) return
      if (Object.keys(headers).length > 0) server.headers = headers
    }
  }
  if (newServerToolTimeout.value.trim()) {
    const t = Number(newServerToolTimeout.value)
    if (!isNaN(t) && t > 0) server.tool_timeout = t
  }
  config.value[name] = server
  expandedServers.value = [...expandedServers.value, name]
  addDialogVisible.value = false
  showToast(`已添加 MCP 服务器 "${name}"（保存后生效）`, 'success', 2000)
}

function removeServer(name: string) {
  const rebuilt: McpConfig = {}
  for (const [k, v] of Object.entries(config.value)) {
    if (k !== name) rebuilt[k] = v
  }
  config.value = rebuilt
  expandedServers.value = expandedServers.value.filter((n) => n !== name)
  showToast(`已删除 MCP 服务器 "${name}"（保存后生效）`, 'success', 2000)
}

// --- Toast ---
function showToast(msg: string, type: 'error' | 'success', duration = 4000) {
  toast.value = { visible: true, message: msg, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value.visible = false
  }, duration)
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
  postMessage({ type: 'getMcpConfig' })
}

onMounted(() => {
  loadConfig()
  unlisten = onMessage((data: any) => {
    switch (data.type) {
      case 'mcpConfig': {
        const { config: cfg, damaged: dmg } = data.payload
        if (loadTimeout) {
          clearTimeout(loadTimeout)
          loadTimeout = null
        }
        loading.value = false
        damaged.value = !!dmg
        if (dmg) {
          config.value = {}
          initialJson.value = '{}'
          expandedServers.value = []
        } else {
          config.value = JSON.parse(JSON.stringify(cfg || {}))
          initialJson.value = JSON.stringify(config.value)
          expandedServers.value = Object.keys(config.value)
        }
        inputDrafts.value = {}
        jsonEditErrors.value = {}
        break
      }
      case 'mcpSaved':
        saving.value = false
        if (saveTimeout) {
          clearTimeout(saveTimeout)
          saveTimeout = null
        }
        saveFailed.value = false
        autoSaveBlocked.value = false
        initialJson.value = JSON.stringify(config.value)
        lastSavedAt.value = new Date()
        showToast('MCP 配置已保存', 'success', 2000)
        break
      case 'mcpError':
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
const isStringMap = (value: unknown): value is Record<string, string> =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.values(value as Record<string, unknown>).every((v) => typeof v === 'string')

const isJsonDirty = (): boolean => Object.keys(jsonEditErrors.value).length > 0

function validateBeforeSave(): string | null {
  if (isJsonDirty()) return '存在未通过校验的 JSON 字段，请修正后再保存'
  for (const [name, server] of Object.entries(config.value)) {
    if (!name.trim()) return 'MCP 服务器名不能为空'
    if (typeof server !== 'object' || server === null) return `服务器 "${name}" 必须是对象`
    const hasCommand = server.command !== undefined
    const hasUrl = server.url !== undefined
    if (!hasCommand && !hasUrl) {
      return `服务器 "${name}" 必须配置 command（stdio）或 url（HTTP）`
    }
    if (hasCommand) {
      if (typeof server.command !== 'string' || !server.command.trim()) return `服务器 "${name}" 的 command 不能为空`
      if (server.args !== undefined && (!Array.isArray(server.args) || server.args.some((a) => typeof a !== 'string')))
        return `服务器 "${name}" 的 args 必须是字符串数组`
      if (server.env !== undefined && !isStringMap(server.env))
        return `服务器 "${name}" 的 env 必须是「字符串 → 字符串」对象`
      if (server.cwd !== undefined && typeof server.cwd !== 'string') return `服务器 "${name}" 的 cwd 必须是字符串`
    }
    if (hasUrl) {
      if (typeof server.url !== 'string' || !server.url.trim()) return `服务器 "${name}" 的 url 不能为空`
      if (server.headers !== undefined && !isStringMap(server.headers))
        return `服务器 "${name}" 的 headers 必须是「字符串 → 字符串」对象`
    }
    if (
      server.tool_timeout !== undefined &&
      (typeof server.tool_timeout !== 'number' || Number.isNaN(server.tool_timeout) || server.tool_timeout <= 0)
    ) {
      return `服务器 "${name}" 的 tool_timeout 必须是正数`
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
    postMessage({ type: 'saveMcpConfig', payload: plainConfig })
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
    <div v-if="damaged" class="damaged-banner">⚠️ 配置文件缺失或损坏，当前显示空配置。保存将创建新文件。</div>

    <!-- Info block -->
    <section class="section" style="background: var(--bg-primary); border-color: var(--border-color)">
      <p class="field-hint">
        MCP（Model Context Protocol）服务器配置。每个服务器需配置 <code>command</code>（stdio）或
        <code>url</code>（HTTP/SSE）之一。
      </p>
      <p class="field-hint">
        读取优先级：<code>{workspace}/.broca/mcp_config.json</code>（工作区）&gt;
        <code>~/.broca/configs/mcp_config.json</code>（全局）。
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
      <div style="font-size: 11px; color: var(--text-secondary)">
        <span v-if="loading">加载中…</span>
        <span v-else-if="saving">保存中…</span>
        <span v-else-if="saveFailed" style="color: #e06060">保存失败，请点击「保存」重试</span>
        <span v-else-if="autoSaveBlocked" style="color: #c0a040">修改未通过校验，暂未保存</span>
        <span v-else-if="lastSavedAt && !dirty">已自动保存 {{ lastSavedAt.toLocaleTimeString() }}</span>
        <span v-else-if="dirty">即将自动保存…</span>
      </div>
      <div style="display: flex; gap: 8px">
        <button class="action-button action-button--secondary" @click="openAddDialog">+ 添加服务器</button>
        <button class="action-button action-button--secondary" :disabled="saving" @click="reset">重置</button>
        <button class="save-button" :disabled="saving || !dirty" @click="saveNow">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-state">加载配置中…</div>

    <!-- Empty -->
    <div v-else-if="serverCount === 0" class="empty-state">
      <p>暂无 MCP 服务器配置</p>
      <p style="margin-top: 4px; font-size: 12px">点击下方按钮添加第一个服务器</p>
      <button class="save-button" style="margin-top: 12px" @click="openAddDialog">+ 添加服务器</button>
    </div>

    <!-- Server list -->
    <template v-else>
      <div v-for="(server, serverName) in config" :key="serverName" class="collapsible">
        <div
          class="collapsible-header"
          @click="
            expandedServers.includes(serverName)
              ? (expandedServers = expandedServers.filter((n) => n !== serverName))
              : expandedServers.push(serverName)
          "
        >
          <span style="font-family: monospace; font-weight: 600">{{ serverName }}</span>
          <span
            style="
              font-size: 11px;
              padding: 1px 6px;
              border-radius: 3px;
              border: 1px solid var(--border-color);
              color: var(--text-secondary);
            "
          >
            {{ transportLabel[transportOf(server)] }}
          </span>
          <span style="flex: 1"></span>
          <button class="delete-btn" title="删除服务器" @click.stop="removeServer(serverName)">✕</button>
          <span style="font-size: 12px; color: var(--text-secondary)">{{
            expandedServers.includes(serverName) ? '▲' : '▼'
          }}</span>
        </div>

        <div v-if="expandedServers.includes(serverName)" class="collapsible-body">
          <div class="field">
            <label class="field-label">服务器名</label>
            <input
              class="field-input"
              :value="getDraft(fieldKey(serverName, 'name'), serverName)"
              @input="setDraft(fieldKey(serverName, 'name'), ($event.target as HTMLInputElement).value)"
              @change="renameServer(serverName, ($event.target as HTMLInputElement).value)"
            />
          </div>

          <div class="field">
            <label class="field-label">传输方式</label>
            <div style="display: flex; gap: 8px">
              <label v-for="t in MCP_TRANSPORTS" :key="t" class="checkbox-row" style="cursor: pointer">
                <input
                  type="radio"
                  :name="`transport-${serverName}`"
                  :checked="transportOf(server) === t"
                  @change="setTransport(server, t)"
                />
                <span class="checkbox-label">{{ transportLabel[t] }}</span>
              </label>
            </div>
          </div>

          <!-- stdio fields -->
          <template v-if="transportOf(server) === 'stdio'">
            <div class="field">
              <label class="field-label">Command</label>
              <input v-model="server.command" class="field-input" placeholder="如 python / npx / uvx" />
            </div>
            <div class="field">
              <label class="field-label">工作目录（cwd，可选）</label>
              <input v-model="server.cwd" class="field-input" placeholder="如 /path/to/server" />
            </div>
            <div class="field">
              <label class="field-label">参数（args，每行一个）</label>
              <textarea
                class="field-textarea"
                rows="3"
                :value="getDraft(fieldKey(serverName, 'args'), argsText(server))"
                placeholder="每行一个参数"
                @input="setDraft(fieldKey(serverName, 'args'), ($event.target as HTMLTextAreaElement).value)"
                @change="applyArgs(serverName, server, ($event.target as HTMLTextAreaElement).value)"
              ></textarea>
            </div>
            <div class="field">
              <label class="field-label">环境变量（env，JSON 对象，可选）</label>
              <textarea
                class="field-textarea"
                rows="3"
                :class="{ 'field-input': true, 'json-error': hasJsonError(fieldKey(serverName, 'env')) }"
                :value="getDraft(fieldKey(serverName, 'env'), stringMapText(server.env))"
                placeholder='{"API_KEY": "xxx"}'
                @input="setDraft(fieldKey(serverName, 'env'), ($event.target as HTMLTextAreaElement).value)"
                @change="applyStringMap(serverName, server, 'env', ($event.target as HTMLTextAreaElement).value)"
              ></textarea>
            </div>
          </template>

          <!-- HTTP fields -->
          <template v-else>
            <div class="field">
              <label class="field-label">URL</label>
              <input v-model="server.url" class="field-input" placeholder="如 https://api.example.com/mcp" />
            </div>
            <div class="field">
              <label class="field-label">请求头（headers，JSON 对象，可选）</label>
              <textarea
                class="field-textarea"
                rows="3"
                :class="{ 'json-error': hasJsonError(fieldKey(serverName, 'headers')) }"
                :value="getDraft(fieldKey(serverName, 'headers'), stringMapText(server.headers))"
                placeholder='{"Authorization": "Bearer xxx"}'
                @input="setDraft(fieldKey(serverName, 'headers'), ($event.target as HTMLTextAreaElement).value)"
                @change="applyStringMap(serverName, server, 'headers', ($event.target as HTMLTextAreaElement).value)"
              ></textarea>
            </div>
          </template>

          <!-- Common -->
          <div class="field">
            <label class="field-label">工具调用超时（tool_timeout，秒，可选）</label>
            <input
              type="number"
              class="field-input"
              style="width: 140px"
              :min="1"
              :value="typeof server.tool_timeout === 'number' ? server.tool_timeout : ''"
              @change="setToolTimeout(server, Number(($event.target as HTMLInputElement).value) || undefined)"
            />
          </div>
        </div>
      </div>
    </template>

    <!-- Add dialog -->
    <div v-if="addDialogVisible" class="modal-overlay" @click.self="addDialogVisible = false">
      <div class="modal" style="max-width: 480px">
        <div class="modal-title">添加 MCP 服务器</div>
        <div class="field">
          <label class="field-label">服务器名</label>
          <input v-model="newServerName" class="field-input" placeholder="如 stock" @keyup.enter="confirmAddServer" />
        </div>
        <div class="field">
          <label class="field-label">传输方式</label>
          <div style="display: flex; gap: 8px">
            <label v-for="t in MCP_TRANSPORTS" :key="t" class="checkbox-row" style="cursor: pointer">
              <input v-model="newServerTransport" type="radio" :value="t" />
              <span class="checkbox-label">{{ transportLabel[t] }}</span>
            </label>
          </div>
        </div>
        <template v-if="newServerTransport === 'stdio'">
          <div class="field">
            <label class="field-label">Command</label>
            <input v-model="newServerCommand" class="field-input" placeholder="如 python / npx / uvx" />
          </div>
          <div class="field">
            <label class="field-label">参数 args（每行一个）</label>
            <textarea v-model="newServerArgs" class="field-textarea" rows="2" placeholder="每行一个参数"></textarea>
          </div>
          <div class="field">
            <label class="field-label">环境变量 env（JSON）</label>
            <textarea
              v-model="newServerEnv"
              class="field-textarea"
              rows="3"
              placeholder='{"API_KEY": "xxx"}'
            ></textarea>
          </div>
        </template>
        <template v-else>
          <div class="field">
            <label class="field-label">URL</label>
            <input v-model="newServerUrl" class="field-input" placeholder="如 https://api.example.com/mcp" />
          </div>
          <div class="field">
            <label class="field-label">请求头 headers（JSON）</label>
            <textarea
              v-model="newServerHeaders"
              class="field-textarea"
              rows="3"
              placeholder='{"Authorization": "Bearer xxx"}'
            ></textarea>
          </div>
        </template>
        <div class="field">
          <label class="field-label">tool_timeout（秒）</label>
          <input
            v-model="newServerToolTimeout"
            type="number"
            class="field-input"
            style="width: 120px"
            min="1"
            placeholder="默认 10"
          />
        </div>
        <div class="modal-actions">
          <button class="action-button action-button--secondary" @click="addDialogVisible = false">取消</button>
          <button class="save-button" @click="confirmAddServer">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.json-error {
  border-color: #e06060 !important;
}
</style>
