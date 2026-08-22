<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Setting, Delete, Loading } from '@element-plus/icons-vue'
import configApi from '@/api/config'
import type { LLMConfig, LLMModelConfig } from '@/api/config'

// ==================== 状态 ====================
const loading = ref(false)
const saving = ref(false)
const config = ref<LLMConfig>({})
const initialJson = ref<string>('{}')
const activeProviders = ref<string[]>([])

// 脏状态：本地修改与初始加载不一致
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)

const providerCount = computed(() => Object.keys(config.value).length)
const modelCount = computed(() =>
  Object.values(config.value).reduce((sum, p) => sum + Object.keys(p.models || {}).length, 0)
)

// ==================== 数据加载 ====================
const loadConfig = async () => {
  loading.value = true
  try {
    const data = await configApi.getLLMConfig()
    // 深拷贝到本地工作副本，避免直接改动接口返回对象
    config.value = JSON.parse(JSON.stringify(data || {}))
    initialJson.value = JSON.stringify(config.value)
    // 默认展开第一个提供商
    const ids = Object.keys(config.value)
    activeProviders.value = ids.length > 0 ? [ids[0]] : []
    // 清理「更多参数」展开状态与 JSON 编辑错误标记
    expandedParams.value = {}
    jsonEditErrors.value = {}
    inputDrafts.value = {}
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  await loadConfig()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  clearAutoSaveTimer()
})

// ==================== 提供商管理 ====================
const providerDialogVisible = ref(false)
const newProviderId = ref('')

const openProviderDialog = () => {
  newProviderId.value = ''
  providerDialogVisible.value = true
}

const confirmAddProvider = () => {
  const id = newProviderId.value.trim()
  if (!id) {
    ElMessage.warning('提供商 ID 不能为空')
    return
  }
  if (id in config.value) {
    ElMessage.warning(`提供商 "${id}" 已存在`)
    return
  }
  config.value[id] = { base_url: '', api_key: '', models: {} }
  activeProviders.value = [...activeProviders.value, id]
  providerDialogVisible.value = false
  ElMessage.success(`已添加提供商 "${id}"，请完善配置后保存`)
}

const removeProvider = async (providerId: string) => {
  const modelNum = Object.keys(config.value[providerId]?.models || {}).length
  try {
    await ElMessageBox.confirm(
      `确定删除提供商 "${providerId}" 吗？${modelNum > 0 ? `其下 ${modelNum} 个模型配置将一并删除。` : ''}`,
      '删除提供商',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  const rebuilt: LLMConfig = {}
  for (const [k, v] of Object.entries(config.value)) {
    if (k !== providerId) rebuilt[k] = v
  }
  config.value = rebuilt
  activeProviders.value = activeProviders.value.filter((id) => id !== providerId)
  ElMessage.success(`已删除提供商 "${providerId}"（保存后生效）`)
}

// ==================== 模型管理 ====================
const modelDialogVisible = ref(false)
const modelDialogProvider = ref('')
const newModelAlias = ref('')
const newModelName = ref('')
const newModelMaxTokens = ref<number | undefined>(undefined)
const newModelContextWindow = ref<number | undefined>(undefined)
/** 添加模型弹窗中勾选的多模态能力 key 列表 */
const newModelModalities = ref<string[]>(['text'])

/** 多模态能力定义：key 为 modality 中的字段名 */
const MODALITY_OPTIONS = [
  { key: 'text', label: '文本' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
  { key: 'audio', label: '音频' },
] as const

/** 判断模型是否启用某项多模态能力（key 存在即启用） */
const hasModality = (modelConfig: LLMModelConfig, key: string): boolean => {
  return Boolean(modelConfig.meta?.modality && key in modelConfig.meta.modality)
}

/** 切换模型的多模态能力：勾选写入 key（text 默认 ""，其余默认 {}），取消则移除 key */
const toggleModality = (modelConfig: LLMModelConfig, key: string, checked: boolean | string | number) => {
  if (!modelConfig.meta || typeof modelConfig.meta !== 'object') {
    modelConfig.meta = {}
  }
  if (!modelConfig.meta.modality || typeof modelConfig.meta.modality !== 'object') {
    modelConfig.meta.modality = {}
  }
  const modality = modelConfig.meta.modality
  if (checked) {
    // 保留已有参数，仅补默认值
    if (!(key in modality)) {
      modality[key] = key === 'text' ? '' : {}
    }
  } else {
    delete modality[key]
  }
}

// ==================== 多模态高级参数对话框 ====================
const modalityDialogVisible = ref(false)
const modalityDialogTarget = ref<{ providerId: string; alias: string; modelConfig: LLMModelConfig } | null>(null)
const modalityImageParams = ref('{}')
const modalityVideoParams = ref('{}')
const modalityAudioParams = ref('{}')

/** 设置模型上下文窗口（表格列内编辑）；meta 缺失时补建最小结构 */
const setContextWindow = (modelConfig: LLMModelConfig, value: number | undefined | null) => {
  if (!modelConfig.meta || typeof modelConfig.meta !== 'object') {
    modelConfig.meta = { modality: {} }
  }
  if (value !== undefined && value !== null) {
    modelConfig.meta.context_window = value
  } else {
    delete modelConfig.meta.context_window
  }
}

const openModalityDialog = (providerId: string, alias: string, modelConfig: LLMModelConfig) => {
  modalityDialogTarget.value = { providerId, alias, modelConfig }
  const meta = modelConfig.meta || {}
  modalityImageParams.value = JSON.stringify(meta.modality?.image ?? {}, null, 2)
  modalityVideoParams.value = JSON.stringify(meta.modality?.video ?? {}, null, 2)
  modalityAudioParams.value = JSON.stringify(meta.modality?.audio ?? {}, null, 2)
  modalityDialogVisible.value = true
}

/** 解析参数 JSON，非法时提示并返回 null */
const parseModalityParams = (raw: string, label: string): Record<string, unknown> | null => {
  try {
    const parsed = JSON.parse(raw || '{}')
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      ElMessage.warning(`${label}参数必须是 JSON 对象`)
      return null
    }
    return parsed as Record<string, unknown>
  } catch {
    ElMessage.warning(`${label}参数不是合法 JSON`)
    return null
  }
}

const confirmModalityDialog = () => {
  const target = modalityDialogTarget.value
  if (!target) return
  const imageParams = parseModalityParams(modalityImageParams.value, '图片')
  if (imageParams === null) return
  const videoParams = parseModalityParams(modalityVideoParams.value, '视频')
  if (videoParams === null) return
  const audioParams = parseModalityParams(modalityAudioParams.value, '音频')
  if (audioParams === null) return

  const modelConfig = target.modelConfig
  if (!modelConfig.meta || typeof modelConfig.meta !== 'object') {
    modelConfig.meta = {}
  }
  if (!modelConfig.meta.modality || typeof modelConfig.meta.modality !== 'object') {
    modelConfig.meta.modality = {}
  }
  const modality = modelConfig.meta.modality
  // 仅同步已启用能力的参数；未启用的能力不写入
  if ('image' in modality) modality.image = imageParams
  if ('video' in modality) modality.video = videoParams
  if ('audio' in modality) modality.audio = audioParams
  modalityDialogVisible.value = false
  ElMessage.success(`已更新模型 "${target.alias}" 的多模态参数（保存后生效）`)
}

const openModelDialog = (providerId: string) => {
  modelDialogProvider.value = providerId
  newModelAlias.value = ''
  newModelName.value = ''
  newModelMaxTokens.value = undefined
  newModelContextWindow.value = undefined
  // 新模型默认启用「文本」能力
  newModelModalities.value = ['text']
  modelDialogVisible.value = true
}

const confirmAddModel = () => {
  const alias = newModelAlias.value.trim()
  const modelName = newModelName.value.trim()
  const providerId = modelDialogProvider.value
  if (!alias) {
    ElMessage.warning('模型别名不能为空')
    return
  }
  if (!modelName) {
    ElMessage.warning('实际模型名不能为空')
    return
  }
  if (newModelModalities.value.length === 0) {
    ElMessage.warning('请至少勾选一项多模态能力')
    return
  }
  const models = config.value[providerId]?.models || {}
  if (alias in models) {
    ElMessage.warning(`模型别名 "${alias}" 已存在`)
    return
  }
  const modality: Record<string, unknown> = {}
  for (const key of newModelModalities.value) {
    // 与列表勾选行为一致：text 默认 ""，其余默认 {}
    modality[key] = key === 'text' ? '' : {}
  }
  const modelConfig: LLMModelConfig = {
    model: modelName,
    meta: { modality },
  }
  if (newModelMaxTokens.value !== undefined && newModelMaxTokens.value !== null) {
    modelConfig.max_tokens = newModelMaxTokens.value
  }
  if (newModelContextWindow.value !== undefined && newModelContextWindow.value !== null) {
    modelConfig.meta.context_window = newModelContextWindow.value
  }
  config.value[providerId].models = { ...models, [alias]: modelConfig }
  modelDialogVisible.value = false
  ElMessage.success(`已添加模型 "${alias}"（保存后生效）`)
}

/** 模型别名重命名：作为 models 的 key，需做 key 迁移（保持原有顺序） */
const renameModel = (providerId: string, oldAlias: string, newAlias: string | number) => {
  const trimmed = String(newAlias).trim()
  const models = config.value[providerId]?.models
  if (!models || !trimmed || trimmed === oldAlias) {
    clearDraft(modelCellKey(providerId, oldAlias, 'alias'))
    return
  }
  if (trimmed in models) {
    ElMessage.warning(`模型别名 "${trimmed}" 已存在`)
    // 触发表格重渲染，恢复输入框显示旧别名
    config.value[providerId].models = { ...models }
    clearDraft(modelCellKey(providerId, oldAlias, 'alias'))
    return
  }
  const rebuilt: Record<string, LLMModelConfig> = {}
  for (const [k, v] of Object.entries(models)) {
    rebuilt[k === oldAlias ? trimmed : k] = v
  }
  config.value[providerId].models = rebuilt
  clearDraft(modelCellKey(providerId, oldAlias, 'alias'))
}

const removeModel = async (providerId: string, alias: string) => {
  try {
    await ElMessageBox.confirm(`确定删除模型 "${alias}" 吗？`, '删除模型', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const models = config.value[providerId]?.models || {}
  const rebuilt: Record<string, LLMModelConfig> = {}
  for (const [k, v] of Object.entries(models)) {
    if (k !== alias) rebuilt[k] = v
  }
  config.value[providerId].models = rebuilt
  ElMessage.success(`已删除模型 "${alias}"（保存后生效）`)
}

// ==================== 更多参数（模型级附加字段） ====================
/** 已有专属编辑入口的字段，不在「更多参数」中重复展示 */
const EXTRA_PARAM_EXCLUDED = new Set(['model', 'max_tokens', 'extra_body', 'meta'])

/** 「更多参数」展开状态：key 为 `${providerId}::${alias}`，默认全部折叠 */
const expandedParams = ref<Record<string, boolean>>({})

/** JSON 编辑错误状态（extra_body 及 JSON 类型附加参数）：key 同上 */
const jsonEditErrors = ref<Record<string, boolean>>({})

const modelCellKey = (providerId: string, alias: string, field = '') =>
  `${providerId}::${alias}${field ? `::${field}` : ''}`

const isParamsExpanded = (providerId: string, alias: string): boolean =>
  Boolean(expandedParams.value[modelCellKey(providerId, alias)])

const toggleParamsExpanded = (providerId: string, alias: string) => {
  const key = modelCellKey(providerId, alias)
  expandedParams.value[key] = !expandedParams.value[key]
}

/** 模型的附加参数键列表（保持配置文件中的字段顺序） */
const extraParamKeys = (modelConfig: LLMModelConfig): string[] =>
  Object.keys(modelConfig).filter((k) => !EXTRA_PARAM_EXCLUDED.has(k))

type ParamValueType = 'boolean' | 'number' | 'string' | 'json'

/** 根据值的类型选择编辑器：布尔→开关、数字→数字输入、字符串→文本、其余(数组/对象/null)→JSON */
const paramValueType = (value: unknown): ParamValueType => {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'string') return 'string'
  return 'json'
}

const setJsonError = (key: string) => {
  jsonEditErrors.value[key] = true
}
const clearJsonError = (key: string) => {
  delete jsonEditErrors.value[key]
}
const hasJsonError = (key: string): boolean => Boolean(jsonEditErrors.value[key])

/**
 * 输入框草稿状态。
 * 这些输入框采用「失焦才写回配置」的交互，若直接把配置值绑到 :model-value，
 * 键入过程中组件重渲染会用旧配置值覆盖 DOM，导致无法输入（字符立即消失）。
 * 因此键入时先写入草稿并回显草稿，失焦提交成功后再清除草稿、显示格式化后的配置值。
 */
const inputDrafts = ref<Record<string, string>>({})

const getDraft = (key: string, fallback: string): string => inputDrafts.value[key] ?? fallback
const setDraft = (key: string, val: string | number) => {
  inputDrafts.value[key] = String(val)
}
const clearDraft = (key: string) => {
  delete inputDrafts.value[key]
}

/** 重命名附加参数键（重建对象以保持字段顺序；alias 不变，展开状态不受影响）。返回是否成功 */
const renameExtraParam = (
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  oldKey: string,
  newKeyRaw: string | number
): boolean => {
  const newKey = String(newKeyRaw).trim()
  if (!newKey || newKey === oldKey) return false
  if (EXTRA_PARAM_EXCLUDED.has(newKey)) {
    ElMessage.warning(`参数名 "${newKey}" 为保留字段，请换一个名称`)
    config.value[providerId].models = { ...(config.value[providerId]?.models || {}) }
    return false
  }
  if (newKey in modelConfig) {
    ElMessage.warning(`参数名 "${newKey}" 已存在`)
    config.value[providerId].models = { ...(config.value[providerId]?.models || {}) }
    return false
  }
  const rebuilt: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(modelConfig)) {
    rebuilt[k === oldKey ? newKey : k] = v
  }
  const models = config.value[providerId]?.models || {}
  config.value[providerId].models = { ...models, [alias]: rebuilt as LLMModelConfig }
  return true
}

/** 提交参数名重命名：无论成功与否都清除草稿（失败时回显旧参数名） */
const commitExtraParamKey = (
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  oldKey: string,
  newKeyRaw: string | number
) => {
  const draftKey = modelCellKey(providerId, alias, `key:${oldKey}`)
  const ok = renameExtraParam(providerId, alias, modelConfig, oldKey, newKeyRaw)
  clearDraft(draftKey)
  if (ok) {
    // 同步迁移该参数值输入框的草稿 key
    const valDraftKey = modelCellKey(providerId, alias, `val:${oldKey}`)
    if (valDraftKey in inputDrafts.value) {
      inputDrafts.value[modelCellKey(providerId, alias, `val:${String(newKeyRaw).trim()}`)] =
        inputDrafts.value[valDraftKey]
      clearDraft(valDraftKey)
    }
  }
}

/** 删除附加参数 */
const removeExtraParam = (modelConfig: LLMModelConfig, key: string) => {
  delete modelConfig[key]
}

/** 更新数字型附加参数；清空输入框视为移除该参数 */
const setNumberParam = (
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  key: string,
  value: number | undefined
) => {
  if (value === undefined || value === null || Number.isNaN(value)) {
    delete modelConfig[key]
    ElMessage.info(`已移除参数 "${key}"`)
    return
  }
  modelConfig[key] = value
}

/** 提交字符串型附加参数（自动识别数字/布尔/JSON），成功后清除草稿 */
const setStringParam = (
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  key: string,
  raw: string | number
) => {
  const text = String(raw).trim()
  if (!text) {
    modelConfig[key] = ''
    clearDraft(modelCellKey(providerId, alias, `val:${key}`))
    return
  }
  try {
    const parsed = JSON.parse(text)
    // 解析结果为非字符串类型（数字/布尔/null/数组/对象）时按解析值存储
    if (typeof parsed !== 'string') {
      modelConfig[key] = parsed
      clearDraft(modelCellKey(providerId, alias, `val:${key}`))
      return
    }
  } catch {
    // 非法 JSON 按普通字符串处理
  }
  modelConfig[key] = text
  clearDraft(modelCellKey(providerId, alias, `val:${key}`))
}

/** 添加参数：弹窗输入参数名，默认值为空字符串 */
const openAddExtraParam = async (providerId: string, alias: string, modelConfig: LLMModelConfig) => {
  let paramName = ''
  try {
    const { value } = await ElMessageBox.prompt('将作为请求参数的键名透传给 LLM', '添加参数', {
      confirmButtonText: '添加',
      cancelButtonText: '取消',
      inputPlaceholder: '如 top_p、reasoning_effort、seed',
      inputValidator: (v: string) => {
        const t = (v || '').trim()
        if (!t) return '参数名不能为空'
        if (EXTRA_PARAM_EXCLUDED.has(t)) return `"${t}" 为保留字段，请换一个名称`
        if (t in modelConfig) return `参数名 "${t}" 已存在`
        return true
      },
    })
    paramName = value.trim()
  } catch {
    return
  }
  modelConfig[paramName] = ''
  // 自动展开该模型的「更多参数」
  expandedParams.value[modelCellKey(providerId, alias)] = true
  ElMessage.success(`已添加参数 "${paramName}"，请填写其值（保存后生效）`)
}

// ==================== extra_body / JSON 类型参数编辑 ====================
/** extra_body 单元格展示文本；未配置时显示占位符 */
const extraBodyText = (modelConfig: LLMModelConfig): string => {
  const body = modelConfig.extra_body
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).length === 0) {
    return ''
  }
  return JSON.stringify(body, null, 2)
}

/** 提交 extra_body 编辑：空串视为清除；非法 JSON 时保留草稿便于继续修改 */
const applyExtraBody = (providerId: string, alias: string, modelConfig: LLMModelConfig, raw: string | number) => {
  const errKey = modelCellKey(providerId, alias, 'extra_body')
  const text = String(raw).trim()
  if (!text) {
    delete modelConfig.extra_body
    clearJsonError(errKey)
    clearDraft(errKey)
    return
  }
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setJsonError(errKey)
      ElMessage.warning('extra_body 必须是 JSON 对象')
      return
    }
    if (Object.keys(parsed).length === 0) {
      delete modelConfig.extra_body
    } else {
      modelConfig.extra_body = parsed as Record<string, unknown>
    }
    clearJsonError(errKey)
    clearDraft(errKey)
  } catch {
    setJsonError(errKey)
    ElMessage.warning('extra_body 不是合法 JSON')
  }
}

/** JSON 类型附加参数的展示文本 */
const jsonParamText = (value: unknown): string => JSON.stringify(value ?? null, null, 2)

/** 提交 JSON 类型附加参数编辑：非法 JSON 时保留草稿便于继续修改 */
const applyJsonParam = (
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  key: string,
  raw: string | number
) => {
  const errKey = modelCellKey(providerId, alias, key)
  const text = String(raw).trim()
  if (!text) {
    setJsonError(errKey)
    ElMessage.warning(`参数 "${key}" 的值不能为空`)
    return
  }
  try {
    modelConfig[key] = JSON.parse(text)
    clearJsonError(errKey)
    clearDraft(modelCellKey(providerId, alias, `val:${key}`))
  } catch {
    setJsonError(errKey)
    ElMessage.warning(`参数 "${key}" 的值不是合法 JSON`)
  }
}

// ==================== 保存（自动 + 手动） ====================
/** 保存前轻量校验，返回错误提示；通过则返回 null */
const validateBeforeSave = (): string | null => {
  for (const [providerId, provider] of Object.entries(config.value)) {
    if (!providerId.trim()) return '提供商 ID 不能为空'
    if (!provider.base_url || !provider.base_url.trim()) {
      return `提供商 "${providerId}" 的 base_url 不能为空`
    }
    if (typeof provider.api_key !== 'string') {
      return `提供商 "${providerId}" 的 api_key 必须为字符串`
    }
    const aliases = Object.keys(provider.models || {})
    if (aliases.some((a) => !a.trim())) {
      return `提供商 "${providerId}" 存在空的模型别名`
    }
    for (const [alias, model] of Object.entries(provider.models || {})) {
      if (!model.model || !String(model.model).trim()) {
        return `模型 "${alias}" 的实际模型名（model）不能为空`
      }
      if (!model.meta || typeof model.meta !== 'object' || !model.meta.modality) {
        return `模型 "${alias}" 缺少多模态配置（meta.modality），请勾选至少保存一次以补全`
      }
      if (
        model.extra_body !== undefined &&
        (typeof model.extra_body !== 'object' || model.extra_body === null || Array.isArray(model.extra_body))
      ) {
        return `模型 "${alias}" 的 extra_body 必须是 JSON 对象`
      }
    }
  }
  return null
}

/** 自动保存防抖延迟（毫秒）：停止编辑该时长后自动保存 */
const AUTO_SAVE_DELAY = 1200

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
/** 保存请求进行期间又发生了修改，完成后需要再排一次自动保存 */
let mutatedDuringSave = false

/** 自动保存被校验阻止：存在非法修改，不能落盘 */
const autoSaveBlocked = ref(false)
/** 最近一次保存失败 */
const saveFailed = ref(false)
/** 最近一次成功保存时间，用于头部状态展示 */
const lastSavedAt = ref<Date | null>(null)

const lastSavedAtText = computed(() =>
  lastSavedAt.value ? lastSavedAt.value.toLocaleTimeString('zh-CN', { hour12: false }) : ''
)

const clearAutoSaveTimer = () => {
  if (autoSaveTimer !== null) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
}

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

/** 落盘保存：成功后以「发起保存时」的内容作为新基线（不重新拉取，避免展开状态等 UI 被重置） */
const persistConfig = async (): Promise<boolean> => {
  const snapshot = JSON.stringify(config.value)
  saving.value = true
  try {
    await configApi.saveLLMConfig(config.value)
    initialJson.value = snapshot
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

/** 自动保存：校验失败时不弹窗轰炸，仅在头部标记状态 */
const runAutoSave = async () => {
  if (!dirty.value || saving.value || loading.value) return
  const error = validateBeforeSave()
  if (error) {
    autoSaveBlocked.value = true
    return
  }
  await persistConfig()
}

/** 手动保存：立即落盘并给出明确反馈 */
const saveConfig = async () => {
  clearAutoSaveTimer()
  const error = validateBeforeSave()
  if (error) {
    ElMessage.warning(error)
    return
  }
  if (await persistConfig()) {
    ElMessage.success('配置已保存（新配置对新启动的 Session 生效）')
  }
}

const resetConfig = async () => {
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('放弃当前未保存的修改并重新加载配置？', '重置', {
        type: 'warning',
        confirmButtonText: '重置',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  clearAutoSaveTimer()
  autoSaveBlocked.value = false
  saveFailed.value = false
  lastSavedAt.value = null
  await loadConfig()
}

// ==================== 离开页面保护 ====================
/** 路由离开：有改动时先自动保存；无法通过校验时询问是否丢弃 */
onBeforeRouteLeave(async () => {
  clearAutoSaveTimer()
  if (!dirty.value) return true
  if (!validateBeforeSave()) {
    return await persistConfig()
  }
  try {
    await ElMessageBox.confirm('当前修改未通过校验、无法自动保存，离开将丢失这些修改。确定离开吗？', '未保存的修改', {
      type: 'warning',
      confirmButtonText: '放弃修改并离开',
      cancelButtonText: '留在本页',
    })
    return true
  } catch {
    return false
  }
})

/** 浏览器刷新/关闭：仍有未落盘的改动时弹出原生确认 */
const handleBeforeUnload = (e: BeforeUnloadEvent) => {
  if (dirty.value || saving.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 页面标题栏 -->
    <div class="sticky top-0 z-10 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-14 sm:h-16">
          <div class="flex items-center gap-2 sm:gap-3 min-w-0">
            <el-icon class="text-blue-600 text-lg sm:text-xl flex-shrink-0"><Setting /></el-icon>
            <h1 class="text-base sm:text-xl font-bold text-gray-900 truncate">LLM 配置管理</h1>
            <!-- 自动保存状态 -->
            <span v-if="saving" class="hidden sm:inline-flex items-center gap-1 text-xs text-blue-600">
              <el-icon class="is-loading"><Loading /></el-icon>
              保存中...
            </span>
            <span v-else-if="saveFailed" class="hidden sm:inline text-xs text-red-500">
              自动保存失败，请点击「保存」重试
            </span>
            <span v-else-if="autoSaveBlocked" class="hidden sm:inline text-xs text-amber-600">
              修改未通过校验，暂未保存
            </span>
            <span v-else-if="lastSavedAt && !dirty" class="hidden md:inline text-xs text-gray-400">
              已自动保存 {{ lastSavedAtText }}
            </span>
            <span v-else-if="dirty" class="hidden sm:inline text-xs text-gray-400">即将自动保存...</span>
          </div>
          <div class="flex items-center gap-2 sm:gap-4 flex-shrink-0">
            <div class="text-sm text-gray-500 hidden md:inline">
              {{ providerCount }} 个提供商 · {{ modelCount }} 个模型
            </div>
            <el-button size="small" :icon="Plus" @click="openProviderDialog">
              <span class="hidden sm:inline">添加提供商</span>
            </el-button>
            <el-button size="small" :icon="Refresh" :disabled="saving" @click="resetConfig">
              <span class="hidden sm:inline">重置</span>
            </el-button>
            <el-button size="small" type="primary" :loading="saving" :disabled="!dirty" @click="saveConfig">
              保存
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">

      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center py-12">
        <el-icon class="is-loading" size="24">
          <Loading />
        </el-icon>
        <span class="ml-2 text-gray-500">加载中...</span>
      </div>

      <!-- 空状态 -->
      <div v-else-if="providerCount === 0" class="flex flex-col items-center justify-center py-12 text-gray-500">
        <el-icon size="48" class="mb-4">
          <Setting />
        </el-icon>
        <p>暂无 LLM 提供商配置</p>
        <p class="text-sm mt-1">点击下方按钮添加第一个提供商</p>
        <el-button class="mt-4" type="primary" :icon="Plus" @click="openProviderDialog">添加提供商</el-button>
      </div>

      <!-- 提供商配置列表 -->
      <el-collapse
        v-else
        v-model="activeProviders"
        class="bg-white rounded-lg border shadow-sm overflow-hidden settings-collapse"
      >
        <el-collapse-item v-for="(provider, providerId) in config" :key="providerId" :name="providerId">
          <template #title>
            <div class="flex items-center gap-2 w-full pr-2">
              <span class="font-semibold text-gray-900">{{ providerId }}</span>
              <el-tag size="small" type="info" effect="plain"
                >{{ Object.keys(provider.models || {}).length }} 个模型</el-tag
              >
              <div class="flex-1"></div>
              <el-button
                size="small"
                type="danger"
                text
                :icon="Delete"
                class="provider-delete-btn"
                @click.stop="removeProvider(providerId)"
              >
                删除提供商
              </el-button>
            </div>
          </template>

          <div class="px-4 pb-4">
            <!-- 提供商基础配置 -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              <div>
                <label class="block text-xs text-gray-600 mb-1">Base URL</label>
                <el-input v-model="provider.base_url" placeholder="https://api.example.com/v1" />
              </div>
              <div>
                <label class="block text-xs text-gray-600 mb-1">API Key</label>
                <el-input v-model="provider.api_key" show-password placeholder="sk-..." />
              </div>
            </div>

            <!-- 模型列表 -->
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-gray-700">模型列表</span>
              <el-button size="small" type="primary" plain :icon="Plus" @click="openModelDialog(providerId)">
                添加模型
              </el-button>
            </div>

            <el-table :data="Object.entries(provider.models || {})" size="small" border>
              <el-table-column label="模型别名" min-width="160">
                <template #default="{ row }">
                  <el-input
                    :model-value="getDraft(modelCellKey(providerId, row[0], 'alias'), row[0])"
                    size="small"
                    @input="(val: string) => setDraft(modelCellKey(providerId, row[0], 'alias'), val)"
                    @change="(val: string | number) => renameModel(providerId, row[0], val)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="实际模型名 (model)" min-width="220">
                <template #default="{ row }">
                  <el-input v-model="row[1].model" size="small" placeholder="openai/model-name" />
                </template>
              </el-table-column>
              <el-table-column label="Max Tokens" width="150">
                <template #default="{ row }">
                  <el-input-number
                    v-model="row[1].max_tokens"
                    size="small"
                    :min="1"
                    :step="1000"
                    controls-position="right"
                    placeholder="默认"
                    style="width: 120px"
                  />
                </template>
              </el-table-column>
              <el-table-column label="上下文窗口" width="160">
                <template #default="{ row }">
                  <el-input-number
                    :model-value="
                      typeof row[1].meta?.context_window === 'number' ? row[1].meta.context_window : undefined
                    "
                    size="small"
                    :min="1"
                    :step="10000"
                    controls-position="right"
                    placeholder="默认"
                    style="width: 130px"
                    @update:model-value="(val: number | undefined) => setContextWindow(row[1], val)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="extra_body" width="230">
                <template #default="{ row }">
                  <el-input
                    type="textarea"
                    :rows="2"
                    :autosize="{ minRows: 2, maxRows: 8 }"
                    class="json-editor font-mono"
                    :class="{ 'json-editor--error': hasJsonError(modelCellKey(providerId, row[0], 'extra_body')) }"
                    :model-value="getDraft(modelCellKey(providerId, row[0], 'extra_body'), extraBodyText(row[1]))"
                    placeholder='未配置，如 {"thinking": {"type": "enabled"}}'
                    @input="(val: string) => setDraft(modelCellKey(providerId, row[0], 'extra_body'), val)"
                    @change="(val: string) => applyExtraBody(providerId, row[0], row[1], val)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="更多参数" width="300" class-name="more-params-cell">
                <template #default="{ row }">
                  <div>
                    <el-button link type="primary" size="small" @click="toggleParamsExpanded(providerId, row[0])">
                      {{ isParamsExpanded(providerId, row[0]) ? '收起' : `展开 (${extraParamKeys(row[1]).length})` }}
                    </el-button>
                    <div v-if="isParamsExpanded(providerId, row[0])" class="mt-2 space-y-2">
                      <div v-for="paramKey in extraParamKeys(row[1])" :key="paramKey" class="flex items-start gap-1">
                        <el-input
                          :model-value="getDraft(modelCellKey(providerId, row[0], `key:${paramKey}`), paramKey)"
                          size="small"
                          class="flex-shrink-0"
                          style="width: 110px"
                          @input="(val: string) => setDraft(modelCellKey(providerId, row[0], `key:${paramKey}`), val)"
                          @change="
                            (val: string | number) => commitExtraParamKey(providerId, row[0], row[1], paramKey, val)
                          "
                        />
                        <!-- 布尔值 → 开关 -->
                        <el-switch
                          v-if="paramValueType(row[1][paramKey]) === 'boolean'"
                          :model-value="Boolean(row[1][paramKey])"
                          size="small"
                          class="mt-1.5"
                          @change="(val: boolean) => (row[1][paramKey] = val)"
                        />
                        <!-- 数字 → 数字输入 -->
                        <el-input-number
                          v-else-if="paramValueType(row[1][paramKey]) === 'number'"
                          :model-value="Number(row[1][paramKey])"
                          size="small"
                          controls-position="right"
                          style="width: 110px"
                          @change="
                            (val: number | undefined) => setNumberParam(providerId, row[0], row[1], paramKey, val)
                          "
                        />
                        <!-- 字符串 → 文本输入（自动识别数字/布尔/JSON） -->
                        <el-input
                          v-else-if="paramValueType(row[1][paramKey]) === 'string'"
                          :model-value="
                            getDraft(modelCellKey(providerId, row[0], `val:${paramKey}`), String(row[1][paramKey]))
                          "
                          size="small"
                          placeholder="文本（自动识别数字/布尔/JSON）"
                          @input="(val: string) => setDraft(modelCellKey(providerId, row[0], `val:${paramKey}`), val)"
                          @change="(val: string) => setStringParam(providerId, row[0], row[1], paramKey, val)"
                        />
                        <!-- 数组/对象/null → JSON 编辑 -->
                        <el-input
                          v-else
                          type="textarea"
                          :rows="2"
                          :autosize="{ minRows: 2, maxRows: 6 }"
                          class="json-editor font-mono"
                          :class="{ 'json-editor--error': hasJsonError(modelCellKey(providerId, row[0], paramKey)) }"
                          :model-value="
                            getDraft(
                              modelCellKey(providerId, row[0], `val:${paramKey}`),
                              jsonParamText(row[1][paramKey])
                            )
                          "
                          @input="(val: string) => setDraft(modelCellKey(providerId, row[0], `val:${paramKey}`), val)"
                          @change="(val: string) => applyJsonParam(providerId, row[0], row[1], paramKey, val)"
                        />
                        <el-button
                          size="small"
                          type="danger"
                          text
                          :icon="Delete"
                          class="flex-shrink-0"
                          @click="removeExtraParam(row[1], paramKey)"
                        />
                      </div>
                      <el-button
                        size="small"
                        type="primary"
                        plain
                        :icon="Plus"
                        @click="openAddExtraParam(providerId, row[0], row[1])"
                      >
                        添加参数
                      </el-button>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="多模态" min-width="210">
                <template #default="{ row }">
                  <div class="flex items-center gap-2 flex-wrap">
                    <el-checkbox
                      v-for="opt in MODALITY_OPTIONS"
                      :key="opt.key"
                      :model-value="hasModality(row[1], opt.key)"
                      size="small"
                      @change="(checked: boolean | string | number) => toggleModality(row[1], opt.key, checked)"
                    >
                      <span class="text-xs">{{ opt.label }}</span>
                    </el-checkbox>
                    <el-button size="small" text type="primary" @click="openModalityDialog(providerId, row[0], row[1])">
                      参数
                    </el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="danger" text :icon="Delete" @click="removeModel(providerId, row[0])" />
                </template>
              </el-table-column>
            </el-table>

            <div v-if="Object.keys(provider.models || {}).length === 0" class="text-center text-gray-400 text-sm py-4">
              暂无模型，点击「添加模型」创建
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 添加提供商对话框 -->
    <el-dialog v-model="providerDialogVisible" title="添加提供商" width="420px">
      <el-form label-width="90px" @submit.prevent>
        <el-form-item label="提供商 ID" required>
          <el-input v-model="newProviderId" placeholder="如 deepseek、openrouter" @keyup.enter="confirmAddProvider" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAddProvider">添加</el-button>
      </template>
    </el-dialog>

    <!-- 添加模型对话框 -->
    <el-dialog v-model="modelDialogVisible" :title="`添加模型（${modelDialogProvider}）`" width="480px">
      <el-form label-width="100px" @submit.prevent>
        <el-form-item label="模型别名" required>
          <el-input v-model="newModelAlias" placeholder="如 deepseek-v4-flash" @keyup.enter="confirmAddModel" />
        </el-form-item>
        <el-form-item label="实际模型名" required>
          <el-input v-model="newModelName" placeholder="如 openai/deepseek-v4-flash" @keyup.enter="confirmAddModel" />
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number
            v-model="newModelMaxTokens"
            :min="1"
            :step="1000"
            controls-position="right"
            placeholder="留空使用默认"
          />
        </el-form-item>
        <el-form-item label="上下文窗口">
          <el-input-number
            v-model="newModelContextWindow"
            :min="1"
            :step="10000"
            controls-position="right"
            placeholder="留空使用默认"
          />
        </el-form-item>
        <el-form-item label="多模态">
          <el-checkbox-group v-model="newModelModalities">
            <el-checkbox v-for="opt in MODALITY_OPTIONS" :key="opt.key" :value="opt.key">
              <span class="text-xs">{{ opt.label }}</span>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <div class="text-xs text-gray-400 px-2">
        默认启用「文本」能力；图片/视频/音频的额外参数可在添加后点击列表中的「参数」配置。temperature
        等其余请求参数可在添加后通过列表中的「更多参数」配置。
      </div>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAddModel">添加</el-button>
      </template>
    </el-dialog>

    <!-- 多模态高级参数对话框 -->
    <el-dialog
      v-model="modalityDialogVisible"
      :title="`多模态参数（${modalityDialogTarget?.alias ?? ''}）`"
      width="520px"
    >
      <div class="text-xs text-gray-500 mb-3">
        勾选能力后可为其配置额外参数（JSON 对象，会合并到对应请求体中，如视频的 <code>{"fp": 2}</code>）。
      </div>
      <el-form label-width="110px" @submit.prevent>
        <el-form-item label="图片参数">
          <el-input
            v-model="modalityImageParams"
            type="textarea"
            :rows="3"
            :disabled="!modalityDialogTarget || !hasModality(modalityDialogTarget.modelConfig, 'image')"
            placeholder="未启用图片能力"
          />
        </el-form-item>
        <el-form-item label="视频参数">
          <el-input
            v-model="modalityVideoParams"
            type="textarea"
            :rows="3"
            :disabled="!modalityDialogTarget || !hasModality(modalityDialogTarget.modelConfig, 'video')"
            placeholder="未启用视频能力"
          />
        </el-form-item>
        <el-form-item label="音频参数">
          <el-input
            v-model="modalityAudioParams"
            type="textarea"
            :rows="3"
            :disabled="!modalityDialogTarget || !hasModality(modalityDialogTarget.modelConfig, 'audio')"
            placeholder="未启用音频能力"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modalityDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmModalityDialog">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.provider-delete-btn {
  margin-left: auto;
}

/* JSON 编辑器：等宽字体 + 错误态红框 */
.json-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.json-editor--error :deep(.el-textarea__inner) {
  border-color: var(--el-color-danger);
}

.json-editor--error :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}

/* collapse 与页面卡片风格统一：去掉自带上下边框，补齐头部内边距 */
.settings-collapse {
  border-top: none;
  border-bottom: none;
}

.settings-collapse :deep(.el-collapse-item__header) {
  padding: 0 16px;
  font-size: 14px;
}

.settings-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

/* 移动端优化 */
@media (max-width: 640px) {
  .settings-collapse :deep(.el-collapse-item__header) {
    padding: 0 12px;
  }
}
</style>
