<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Loading, Delete, WarningFilled, InfoFilled, Setting } from '@element-plus/icons-vue'
import configApi, { MCP_TRANSPORTS, type McpConfig, type McpServerConfig, type McpTransport } from '@/api/config'

// ==================== 状态 ====================
const loading = ref(false)
const saving = ref(false)
const config = ref<McpConfig>({})
const initialJson = ref<string>('{}')
/** 文件缺失或损坏：显示警示条，保存将创建/修复文件 */
const damaged = ref(false)

/** 当前文件路径（只读展示） */
const configPath = '~/.broca/configs/mcp_config.json'

// 脏状态：本地修改与初始加载/基线不一致
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)

const serverCount = computed(() => Object.keys(config.value).length)

// 自动保存状态（语义与 Settings.vue 一致）
const saveFailed = ref(false)
const autoSaveBlocked = ref(false)
const lastSavedAt = ref<Date | null>(null)
const lastSavedAtText = computed(() =>
  lastSavedAt.value ? lastSavedAt.value.toLocaleTimeString('zh-CN', { hour12: false }) : ''
)

// ==================== 草稿状态（失焦才写回配置） ====================
/**
 * 与 Settings.vue 相同的交互约定：JSON / 多行文本框在键入时只写入草稿，
 * 失焦（change）时解析提交；避免组件重渲染用旧配置值覆盖 DOM 导致无法输入。
 */
const inputDrafts = ref<Record<string, string>>({})
const jsonEditErrors = ref<Record<string, boolean>>({})

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

// 展开状态：默认全部展开，方便编辑
const expandedServers = ref<string[]>([])

// ==================== 传输方式辅助 ====================
const transportOf = (server: McpServerConfig): McpTransport => (server.url && !server.command ? 'http' : 'stdio')

const transportLabel: Record<McpTransport, string> = { stdio: 'stdio', http: 'HTTP' }

/** 切换传输方式：清理另一种传输的专属字段，避免命令/URL 同时存在导致歧义 */
const setTransport = (server: McpServerConfig, transport: McpTransport) => {
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

// ==================== 字段 <-> 文本转换 ====================
const argsText = (server: McpServerConfig): string => (server.args || []).join('\n')

const applyArgs = (serverName: string, server: McpServerConfig, text: string) => {
  const args = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
  if (args.length > 0) {
    server.args = args
  } else {
    delete server.args
  }
  clearDraft(fieldKey(serverName, 'args'))
}

const stringMapText = (value: Record<string, string> | undefined): string => JSON.stringify(value ?? {}, null, 2)

/** 解析 string→string 的 JSON 对象文本；非法时返回 null（并提示） */
const parseStringMapText = (text: string, label: string): Record<string, string> | null => {
  let parsed: unknown
  try {
    parsed = JSON.parse(text || '{}')
  } catch {
    ElMessage.warning(`${label}不是合法 JSON`)
    return null
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    ElMessage.warning(`${label}必须是 JSON 对象`)
    return null
  }
  const map: Record<string, string> = {}
  for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
    if (typeof v !== 'string') {
      ElMessage.warning(`${label}的值必须都是字符串`)
      return null
    }
    map[k] = v
  }
  return map
}

/** 解析 string→string 的 JSON 对象；非法时标记错误并保留草稿 */
const applyStringMap = (serverName: string, server: McpServerConfig, field: 'env' | 'headers', text: string) => {
  const key = fieldKey(serverName, field)
  const label = field === 'env' ? '环境变量' : '请求头'
  const map = parseStringMapText(text, label)
  if (map === null) {
    setJsonError(key)
    return
  }
  if (Object.keys(map).length > 0) {
    server[field] = map
  } else {
    delete server[field]
  }
  clearJsonError(key)
  clearDraft(key)
}

/** 设置/清除 tool_timeout（数值型） */
const setToolTimeout = (server: McpServerConfig, value: number | undefined | null) => {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    delete server.tool_timeout
  } else {
    server.tool_timeout = Number(value)
  }
}

// ==================== 服务器名重命名 ====================
const renameServer = (oldName: string, newNameRaw: string | number) => {
  const newName = String(newNameRaw).trim()
  if (!newName || newName === oldName) {
    clearDraft(fieldKey(oldName, 'name'))
    // 触发重渲染，恢复输入框显示旧名称
    config.value = { ...config.value }
    return
  }
  if (newName in config.value) {
    ElMessage.warning(`服务器 "${newName}" 已存在`)
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

// ==================== 服务器增删 ====================
const addDialogVisible = ref(false)
const newServerName = ref('')
const newServerTransport = ref<McpTransport>('stdio')
const newServerCommand = ref('')
const newServerArgs = ref('')
const newServerEnv = ref('')
const newServerUrl = ref('')
const newServerHeaders = ref('')
const newServerToolTimeout = ref<number | undefined>(undefined)

const openAddDialog = () => {
  newServerName.value = ''
  newServerTransport.value = 'stdio'
  newServerCommand.value = ''
  newServerArgs.value = ''
  newServerEnv.value = ''
  newServerUrl.value = ''
  newServerHeaders.value = ''
  newServerToolTimeout.value = undefined
  addDialogVisible.value = true
}

const confirmAddServer = () => {
  const name = newServerName.value.trim()
  if (!name) {
    ElMessage.warning('服务器名不能为空')
    return
  }
  if (name in config.value) {
    ElMessage.warning(`服务器 "${name}" 已存在`)
    return
  }
  if (newServerTransport.value === 'stdio' && !newServerCommand.value.trim()) {
    ElMessage.warning('stdio 传输需要填写 command')
    return
  }
  if (newServerTransport.value === 'http' && !newServerUrl.value.trim()) {
    ElMessage.warning('HTTP 传输需要填写 url')
    return
  }

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
  if (newServerToolTimeout.value !== undefined && newServerToolTimeout.value !== null) {
    server.tool_timeout = newServerToolTimeout.value
  }
  config.value[name] = server
  expandedServers.value = [...expandedServers.value, name]
  addDialogVisible.value = false
  ElMessage.success(`已添加 MCP 服务器 "${name}"（保存后生效）`)
}

const removeServer = async (name: string) => {
  try {
    await ElMessageBox.confirm(`确定删除 MCP 服务器 "${name}" 吗？`, '删除服务器', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const rebuilt: McpConfig = {}
  for (const [k, v] of Object.entries(config.value)) {
    if (k !== name) rebuilt[k] = v
  }
  config.value = rebuilt
  expandedServers.value = expandedServers.value.filter((n) => n !== name)
  ElMessage.success(`已删除 MCP 服务器 "${name}"（保存后生效）`)
}

// ==================== 数据加载 ====================
const loadConfig = async () => {
  loading.value = true
  try {
    const data = await configApi.getMcpConfig()
    config.value = JSON.parse(JSON.stringify(data || {}))
    initialJson.value = JSON.stringify(config.value)
    expandedServers.value = Object.keys(config.value)
    inputDrafts.value = {}
    jsonEditErrors.value = {}
    damaged.value = false
  } catch {
    // 文件缺失（404）或损坏（500）：用空配置继续编辑，保存将创建/修复文件
    config.value = {}
    initialJson.value = '{}'
    expandedServers.value = []
    inputDrafts.value = {}
    jsonEditErrors.value = {}
    damaged.value = true
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadConfig()
})

// ==================== 自动保存 ====================
const AUTO_SAVE_DELAY = 1200

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
/** 保存请求进行期间又发生了修改，完成后需要再排一次自动保存 */
let mutatedDuringSave = false

const clearAutoSaveTimer = () => {
  if (autoSaveTimer !== null) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
}

onBeforeUnmount(clearAutoSaveTimer)

/** 防抖调度自动保存：每次修改后重置计时 */
const scheduleAutoSave = () => {
  clearAutoSaveTimer()
  if (loading.value || !dirty.value) return
  autoSaveTimer = setTimeout(() => {
    autoSaveTimer = null
    void runAutoSave()
  }, AUTO_SAVE_DELAY)
}

// 深度监听配置变化，驱动自动保存
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

// ==================== 校验与保存 ====================
/** 保存前校验，返回错误提示；通过则返回 null（与后端 _validate_mcp_config 规则一致） */
const validateBeforeSave = (): string | null => {
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
      if (typeof server.command !== 'string' || !server.command.trim()) {
        return `服务器 "${name}" 的 command 不能为空`
      }
      if (
        server.args !== undefined &&
        (!Array.isArray(server.args) || server.args.some((a) => typeof a !== 'string'))
      ) {
        return `服务器 "${name}" 的 args 必须是字符串数组`
      }
      for (const field of ['env'] as const) {
        const map = server[field]
        if (map !== undefined && !isStringMap(map)) {
          return `服务器 "${name}" 的 ${field} 必须是「字符串 → 字符串」对象`
        }
      }
      if (server.cwd !== undefined && typeof server.cwd !== 'string') {
        return `服务器 "${name}" 的 cwd 必须是字符串`
      }
    }
    if (hasUrl) {
      if (typeof server.url !== 'string' || !server.url.trim()) {
        return `服务器 "${name}" 的 url 不能为空`
      }
      if (server.headers !== undefined && !isStringMap(server.headers)) {
        return `服务器 "${name}" 的 headers 必须是「字符串 → 字符串」对象`
      }
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

const isStringMap = (value: unknown): value is Record<string, string> =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.values(value as Record<string, unknown>).every((v) => typeof v === 'string')

/** 是否存在未解决的 JSON 编辑错误（草稿非法） */
const isJsonDirty = (): boolean => Object.keys(jsonEditErrors.value).length > 0

const emit = defineEmits<{ (e: 'dirty-change', dirty: boolean): void }>()

// 当 dirty 变化时上报父组件（聚合离开保护）
watch(dirty, (val) => emit('dirty-change', val))

/** 落盘保存：成功后以「发起保存时」的内容作为新基线 */
const persistConfig = async (): Promise<boolean> => {
  const snapshot = JSON.stringify(config.value)
  saving.value = true
  try {
    await configApi.saveMcpConfig(config.value)
    initialJson.value = snapshot
    damaged.value = false
    lastSavedAt.value = new Date()
    saveFailed.value = false
    autoSaveBlocked.value = false
    return true
  } catch {
    // 错误提示由 request 拦截器统一弹出
    saveFailed.value = true
    return false
  } finally {
    saving.value = false
    // 保存期间又有修改：再排一次自动保存
    if (mutatedDuringSave) {
      mutatedDuringSave = false
      scheduleAutoSave()
    }
  }
}

/** 自动保存：校验失败时不弹窗轰炸，仅在工具栏标记状态 */
const runAutoSave = async () => {
  if (!dirty.value || saving.value || loading.value) return
  const error = validateBeforeSave()
  if (error) {
    autoSaveBlocked.value = true
    return
  }
  await persistConfig()
}

/** 手动/离开前保存：立即落盘并返回是否成功 */
const saveNow = async (): Promise<boolean> => {
  clearAutoSaveTimer()
  const error = validateBeforeSave()
  if (error) {
    ElMessage.warning(error)
    return false
  }
  const ok = await persistConfig()
  if (ok) {
    ElMessage.success('MCP 配置已保存（新配置对新启动的服务生效）')
  }
  return ok
}

/** 重置：重新加载文件内容并清除脏状态 */
const reset = async () => {
  clearAutoSaveTimer()
  autoSaveBlocked.value = false
  saveFailed.value = false
  lastSavedAt.value = null
  await loadConfig()
}

defineExpose({ saveNow, reset })
</script>

<template>
  <div>
    <!-- 警示条：文件缺失/损坏 -->
    <div
      v-if="damaged"
      class="flex items-start gap-2 mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700"
    >
      <el-icon class="mt-0.5 flex-shrink-0"><WarningFilled /></el-icon>
      <div>
        <p class="font-medium">配置文件缺失或损坏（JSON 解析失败）</p>
        <p class="mt-1">当前显示空配置。保存将创建新文件，或先备份损坏文件再修复。</p>
      </div>
    </div>

    <!-- 只读说明块 -->
    <div
      class="flex items-start gap-2 mb-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700"
    >
      <el-icon class="mt-0.5 flex-shrink-0"><InfoFilled /></el-icon>
      <div>
        <p>
          MCP（Model Context Protocol）服务器配置。每个服务器需配置
          <code>command</code>（stdio 子进程）或 <code>url</code>（HTTP/SSE）之一。
        </p>
        <p class="mt-1">
          读取优先级：<code>{workspace}/.broca/mcp_config.json</code>（工作区，最高） &gt;
          <code>~/.broca/configs/mcp_config.json</code>（全局，本页编辑此文件）。
        </p>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex items-center gap-2 sm:gap-3 min-w-0 flex-wrap">
        <!-- 自动保存状态 -->
        <span v-if="saving" class="inline-flex items-center gap-1 text-xs text-blue-600">
          <el-icon class="is-loading"><Loading /></el-icon>
          保存中...
        </span>
        <span v-else-if="saveFailed" class="text-xs text-red-500">保存失败，请点击「保存」重试</span>
        <span v-else-if="autoSaveBlocked" class="text-xs text-amber-600">修改未通过校验，暂未保存</span>
        <span v-else-if="lastSavedAt && !dirty" class="text-xs text-gray-400">已自动保存 {{ lastSavedAtText }}</span>
        <span v-else-if="dirty" class="text-xs text-gray-400">即将自动保存...</span>
      </div>
      <div class="flex items-center gap-2 sm:gap-4 flex-shrink-0 flex-wrap">
        <span class="text-xs text-gray-400 hidden md:inline"
          >文件：<code class="font-mono">{{ configPath }}</code></span
        >
        <el-button size="small" type="primary" plain :icon="Plus" @click="openAddDialog">添加服务器</el-button>
        <el-button size="small" :icon="Refresh" :disabled="saving" @click="reset">重置</el-button>
        <el-button size="small" type="primary" :loading="saving" :disabled="!dirty" @click="saveNow">保存</el-button>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="serverCount === 0" class="flex flex-col items-center justify-center py-12 text-gray-500">
      <el-icon size="48" class="mb-4"><Setting /></el-icon>
      <p>暂无 MCP 服务器配置</p>
      <p class="text-sm mt-1">点击下方按钮添加第一个服务器</p>
      <el-button class="mt-4" type="primary" :icon="Plus" @click="openAddDialog">添加服务器</el-button>
    </div>

    <!-- 服务器列表 -->
    <el-collapse
      v-else
      v-model="expandedServers"
      class="bg-white rounded-lg border shadow-sm overflow-hidden settings-collapse"
    >
      <el-collapse-item v-for="(server, serverName) in config" :key="serverName" :name="serverName">
        <template #title>
          <div class="flex items-center gap-2 w-full pr-2">
            <span class="font-semibold text-gray-900 font-mono">{{ serverName }}</span>
            <el-tag size="small" :type="transportOf(server) === 'stdio' ? 'info' : 'success'" effect="plain">
              {{ transportLabel[transportOf(server)] }}
            </el-tag>
            <div class="flex-1"></div>
            <el-button
              size="small"
              type="danger"
              text
              :icon="Delete"
              class="provider-delete-btn"
              @click.stop="removeServer(serverName)"
            >
              删除服务器
            </el-button>
          </div>
        </template>

        <div class="px-4 pb-4 space-y-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- 服务器名 -->
            <div>
              <label class="block text-xs text-gray-600 mb-1">服务器名</label>
              <el-input
                :model-value="getDraft(fieldKey(serverName, 'name'), serverName)"
                placeholder="如 stock"
                @input="(val: string) => setDraft(fieldKey(serverName, 'name'), val)"
                @change="(val: string | number) => renameServer(serverName, val)"
              />
            </div>
            <!-- 传输方式 -->
            <div>
              <label class="block text-xs text-gray-600 mb-1">传输方式</label>
              <el-radio-group
                :model-value="transportOf(server)"
                @change="(val: string | number | boolean | undefined) => setTransport(server, val as McpTransport)"
              >
                <el-radio-button v-for="t in MCP_TRANSPORTS" :key="t" :value="t">
                  {{ transportLabel[t] }}
                </el-radio-button>
              </el-radio-group>
            </div>
          </div>

          <!-- stdio 专属字段 -->
          <template v-if="transportOf(server) === 'stdio'">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs text-gray-600 mb-1">Command</label>
                <el-input v-model="server.command" placeholder="如 python / npx / uvx" />
              </div>
              <div>
                <label class="block text-xs text-gray-600 mb-1">工作目录（cwd，可选）</label>
                <el-input v-model="server.cwd" placeholder="如 /path/to/server" />
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-600 mb-1">参数（args，每行一个）</label>
              <el-input
                type="textarea"
                :rows="2"
                :autosize="{ minRows: 2, maxRows: 8 }"
                class="font-mono"
                :model-value="getDraft(fieldKey(serverName, 'args'), argsText(server))"
                placeholder="每行一个参数，如&#10;stock_mcp_server.py&#10;--verbose"
                @input="(val: string) => setDraft(fieldKey(serverName, 'args'), val)"
                @change="(val: string) => applyArgs(serverName, server, val)"
              />
            </div>
            <div>
              <label class="block text-xs text-gray-600 mb-1">环境变量（env，JSON 对象，可选）</label>
              <el-input
                type="textarea"
                :rows="3"
                :autosize="{ minRows: 3, maxRows: 10 }"
                class="json-editor font-mono"
                :class="{ 'json-editor--error': hasJsonError(fieldKey(serverName, 'env')) }"
                :model-value="getDraft(fieldKey(serverName, 'env'), stringMapText(server.env))"
                placeholder='如 {"API_KEY": "xxx"}'
                @input="(val: string) => setDraft(fieldKey(serverName, 'env'), val)"
                @change="(val: string) => applyStringMap(serverName, server, 'env', val)"
              />
            </div>
          </template>

          <!-- HTTP 专属字段 -->
          <template v-else>
            <div>
              <label class="block text-xs text-gray-600 mb-1">URL</label>
              <el-input v-model="server.url" placeholder="如 https://api.example.com/mcp" />
            </div>
            <div>
              <label class="block text-xs text-gray-600 mb-1">请求头（headers，JSON 对象，可选）</label>
              <el-input
                type="textarea"
                :rows="3"
                :autosize="{ minRows: 3, maxRows: 10 }"
                class="json-editor font-mono"
                :class="{ 'json-editor--error': hasJsonError(fieldKey(serverName, 'headers')) }"
                :model-value="getDraft(fieldKey(serverName, 'headers'), stringMapText(server.headers))"
                placeholder='如 {"Authorization": "Bearer xxx"}'
                @input="(val: string) => setDraft(fieldKey(serverName, 'headers'), val)"
                @change="(val: string) => applyStringMap(serverName, server, 'headers', val)"
              />
            </div>
          </template>

          <!-- 通用字段 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-gray-600 mb-1">工具调用超时（tool_timeout，秒，可选）</label>
              <el-input-number
                :model-value="typeof server.tool_timeout === 'number' ? server.tool_timeout : undefined"
                :min="1"
                :step="5"
                controls-position="right"
                style="width: 160px"
                placeholder="默认 10"
                @update:model-value="(val: number | undefined) => setToolTimeout(server, val)"
              />
            </div>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 添加服务器对话框 -->
    <el-dialog v-model="addDialogVisible" title="添加 MCP 服务器" width="540px">
      <el-form label-width="120px" @submit.prevent>
        <el-form-item label="服务器名" required>
          <el-input v-model="newServerName" placeholder="如 stock" @keyup.enter="confirmAddServer" />
        </el-form-item>
        <el-form-item label="传输方式">
          <el-radio-group v-model="newServerTransport">
            <el-radio-button v-for="t in MCP_TRANSPORTS" :key="t" :value="t">
              {{ transportLabel[t] }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="newServerTransport === 'stdio'">
          <el-form-item label="Command" required>
            <el-input v-model="newServerCommand" placeholder="如 python / npx / uvx" />
          </el-form-item>
          <el-form-item label="参数 args">
            <el-input
              v-model="newServerArgs"
              type="textarea"
              :rows="2"
              :autosize="{ minRows: 2, maxRows: 8 }"
              class="font-mono"
              placeholder="每行一个参数，如&#10;stock_mcp_server.py&#10;--verbose"
            />
          </el-form-item>
          <el-form-item label="环境变量 env">
            <el-input
              v-model="newServerEnv"
              type="textarea"
              :rows="3"
              :autosize="{ minRows: 3, maxRows: 10 }"
              class="json-editor font-mono"
              placeholder='JSON 对象，如 {"API_KEY": "xxx"}'
            />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="URL" required>
            <el-input v-model="newServerUrl" placeholder="如 https://api.example.com/mcp" />
          </el-form-item>
          <el-form-item label="请求头 headers">
            <el-input
              v-model="newServerHeaders"
              type="textarea"
              :rows="3"
              :autosize="{ minRows: 3, maxRows: 10 }"
              class="json-editor font-mono"
              placeholder='JSON 对象，如 {"Authorization": "Bearer xxx"}'
            />
          </el-form-item>
        </template>
        <el-form-item label="tool_timeout">
          <el-input-number
            v-model="newServerToolTimeout"
            :min="1"
            :step="5"
            controls-position="right"
            style="width: 160px"
            placeholder="默认 10"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAddServer">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>
