<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { postMessage, onMessage } from '../../api/vscode'
import type { LLMConfig, LLMModelConfig, LLMDefaultConfig, LLMWireConfig } from '../../types'
import { LLM_DEFAULT_KEY } from '../../types'

import './settings.css'

// ==================== State ====================
const loading = ref(false)
const saving = ref(false)
const config = ref<LLMConfig>({})
// 全局默认 provider/model（对应 llm_config.json 中的 __default__ 保留键）
const llmDefault = ref<LLMDefaultConfig>({ provider: '', model: '' })
const initialJson = ref('{}')
const activeProviders = ref<string[]>([])
// 组装完整配置（提供商 + 可选 __default__）；__default__ 仅含 provider/model 两个字符串，
// 可安全 JSON 序列化参与脏检测
const buildFullConfig = (): LLMWireConfig => {
  const full: LLMWireConfig = { ...config.value }
  if (llmDefault.value.provider) full[LLM_DEFAULT_KEY] = { ...llmDefault.value }
  return full
}
// 脏检测需同时覆盖提供商配置与默认 provider/model
const dirty = computed(() => JSON.stringify(buildFullConfig()) !== initialJson.value)
const providerCount = computed(() => Object.keys(config.value).length)
const modelCount = computed(() =>
  Object.values(config.value).reduce((sum, p) => sum + Object.keys(p.models || {}).length, 0)
)
const saveFailed = ref(false)
const autoSaveBlocked = ref(false)
const lastSavedAt = ref<Date | null>(null)
const toast = ref({ visible: false, message: '', type: 'error' as 'error' | 'success' })
let toastTimer: ReturnType<typeof setTimeout> | null = null
let unlisten: (() => void) | null = null
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let loadTimeout: ReturnType<typeof setTimeout> | null = null
let saveTimeout: ReturnType<typeof setTimeout> | null = null
let mutatedDuringSave = false

// 默认 provider/model 下拉的选项来源
const providerIds = computed(() => Object.keys(config.value))
const defaultModelOptions = computed(() =>
  llmDefault.value.provider ? Object.keys(config.value[llmDefault.value.provider]?.models || {}) : []
)

const loadError = ref('')

// ==================== Dialogs ====================
const providerDialogVisible = ref(false)
const newProviderId = ref('')
const modelDialogVisible = ref(false)
const modelDialogProvider = ref('')
const newModelAlias = ref('')
const newModelName = ref('')
const newModelMaxTokens = ref<string>('')
const newModelContextWindow = ref<string>('')
const newModelModalities = ref<string[]>(['text'])
const showApiKey = ref<Record<string, boolean>>({})

// Modality params dialog
const modalityDialogVisible = ref(false)
const modalityDialogTarget = ref<{ providerId: string; alias: string; modelConfig: LLMModelConfig } | null>(null)
const modalityImageParams = ref('{}')
const modalityVideoParams = ref('{}')
const modalityAudioParams = ref('{}')

// Add extra param dialog
const extraParamDialogVisible = ref(false)
const extraParamTarget = ref<{ providerId: string; alias: string; modelConfig: LLMModelConfig } | null>(null)
const newExtraParamKey = ref('')

const MODALITY_OPTIONS = [
  { key: 'text', label: '文本' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
  { key: 'audio', label: '音频' },
] as const

// ==================== Toast ====================
function showToast(msg: string, type: 'error' | 'success', duration = 4000) {
  toast.value = { visible: true, message: msg, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value.visible = false
  }, duration)
}

// ==================== Load ====================
function loadConfig() {
  loading.value = true
  loadError.value = ''
  if (loadTimeout) clearTimeout(loadTimeout)
  loadTimeout = setTimeout(() => {
    if (loading.value) {
      loading.value = false
      loadError.value = '加载超时，请检查服务器是否运行'
    }
  }, 8000)
  postMessage({ type: 'getLLMConfig' })
}

onMounted(() => {
  loadConfig()
  unlisten = onMessage((data: any) => {
    switch (data.type) {
      case 'llmConfig': {
        const { config: cfg, damaged: dmg } = data.payload
        if (loadTimeout) {
          clearTimeout(loadTimeout)
          loadTimeout = null
        }
        loading.value = false
        if (dmg) {
          config.value = {}
          llmDefault.value = { provider: '', model: '' }
          initialJson.value = '{}'
          activeProviders.value = []
        } else {
          // 拆出保留键 __default__（全局默认 provider/model），其余为提供商配置
          const wire = JSON.parse(JSON.stringify(cfg || {}))
          const defaultRaw = (wire as Record<string, unknown>)[LLM_DEFAULT_KEY]
          delete (wire as Record<string, unknown>)[LLM_DEFAULT_KEY]
          config.value = wire
          const def = (defaultRaw as LLMDefaultConfig) || {}
          llmDefault.value = { provider: def.provider || '', model: def.model || '' }
          // 防御：provider 已设但 model 为空 → 补该提供商的首个模型，保持成对
          if (llmDefault.value.provider && !llmDefault.value.model) {
            const first = Object.keys(config.value[llmDefault.value.provider]?.models || {})[0]
            if (first) llmDefault.value.model = first
          }
          initialJson.value = JSON.stringify(buildFullConfig())
          const ids = Object.keys(config.value)
          activeProviders.value = ids.length > 0 ? [ids[0]] : []
        }
        expandedParams.value = {}
        jsonEditErrors.value = {}
        inputDrafts.value = {}
        break
      }
      case 'llmConfigSaved':
        saving.value = false
        if (saveTimeout) {
          clearTimeout(saveTimeout)
          saveTimeout = null
        }
        saveFailed.value = false
        autoSaveBlocked.value = false
        initialJson.value = JSON.stringify(config.value)
        lastSavedAt.value = new Date()
        showToast('LLM 配置已保存', 'success', 2000)
        break
      case 'llmConfigError':
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
        if (initialJson.value === '{}') {
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
  if (loadTimeout) clearTimeout(loadTimeout)
  if (saveTimeout) clearTimeout(saveTimeout)
  clearAutoSaveTimer()
})

// ==================== Provider management ====================
function openProviderDialog() {
  newProviderId.value = ''
  providerDialogVisible.value = true
}

function confirmAddProvider() {
  const id = newProviderId.value.trim()
  if (!id) return showToast('提供商 ID 不能为空', 'error')
  if (id in config.value) return showToast(`提供商 "${id}" 已存在`, 'error')
  config.value[id] = { base_url: '', api_key: '', models: {} }
  activeProviders.value = [...activeProviders.value, id]
  providerDialogVisible.value = false
  showToast(`已添加提供商 "${id}"`, 'success', 2000)
}

function removeProvider(providerId: string) {
  const modelNum = Object.keys(config.value[providerId]?.models || {}).length
  const rebuilt: LLMConfig = {}
  for (const [k, v] of Object.entries(config.value)) {
    if (k !== providerId) rebuilt[k] = v
  }
  config.value = rebuilt
  activeProviders.value = activeProviders.value.filter((id) => id !== providerId)
  // 若默认配置引用了该提供商，清空默认，避免指向已删除的提供商
  if (llmDefault.value.provider === providerId) {
    llmDefault.value = { provider: '', model: '' }
  }
  showToast(`已删除提供商 "${providerId}"`, 'success', 2000)
}

// ==================== Model management ====================
function openModelDialog(providerId: string) {
  modelDialogProvider.value = providerId
  newModelAlias.value = ''
  newModelName.value = ''
  newModelMaxTokens.value = ''
  newModelContextWindow.value = ''
  newModelModalities.value = ['text']
  modelDialogVisible.value = true
}

function confirmAddModel() {
  const alias = newModelAlias.value.trim()
  const modelName = newModelName.value.trim()
  const providerId = modelDialogProvider.value
  if (!alias) return showToast('模型别名不能为空', 'error')
  if (!modelName) return showToast('实际模型名不能为空', 'error')
  if (newModelModalities.value.length === 0) return showToast('请至少勾选一项多模态能力', 'error')
  const models = config.value[providerId]?.models || {}
  if (alias in models) return showToast(`模型别名 "${alias}" 已存在`, 'error')

  const modality: Record<string, unknown> = {}
  for (const key of newModelModalities.value) {
    modality[key] = key === 'text' ? '' : {}
  }
  const modelConfig: LLMModelConfig = { model: modelName, meta: { modality } }
  if (newModelMaxTokens.value.trim()) {
    const mt = Number(newModelMaxTokens.value)
    if (!isNaN(mt)) modelConfig.max_tokens = mt
  }
  if (newModelContextWindow.value.trim()) {
    const cw = Number(newModelContextWindow.value)
    if (!isNaN(cw)) modelConfig.meta.context_window = cw
  }
  config.value[providerId].models = { ...models, [alias]: modelConfig }
  modelDialogVisible.value = false
  showToast(`已添加模型 "${alias}"`, 'success', 2000)
}

function removeModel(providerId: string, alias: string) {
  const models = config.value[providerId]?.models || {}
  const rebuilt: Record<string, LLMModelConfig> = {}
  for (const [k, v] of Object.entries(models)) {
    if (k !== alias) rebuilt[k] = v
  }
  config.value[providerId].models = rebuilt
  // 若默认模型正是被删除的模型，重新指向剩余首个或清空
  if (llmDefault.value.provider === providerId && llmDefault.value.model === alias) {
    const first = Object.keys(rebuilt)[0]
    if (first) llmDefault.value.model = first
    else llmDefault.value = { provider: '', model: '' }
  }
  showToast(`已删除模型 "${alias}"`, 'success', 2000)
}

// ==================== Modality ====================
const hasModality = (modelConfig: LLMModelConfig, key: string): boolean =>
  Boolean(modelConfig.meta?.modality && key in modelConfig.meta.modality)

function toggleModality(modelConfig: LLMModelConfig, key: string, checked: boolean) {
  if (!modelConfig.meta || typeof modelConfig.meta !== 'object') modelConfig.meta = {}
  if (!modelConfig.meta.modality || typeof modelConfig.meta.modality !== 'object') modelConfig.meta.modality = {}
  const modality = modelConfig.meta.modality as Record<string, unknown>
  if (checked) {
    if (!(key in modality)) modality[key] = key === 'text' ? '' : {}
  } else {
    delete modality[key]
  }
}

function setContextWindow(modelConfig: LLMModelConfig, value: number | undefined | null) {
  if (!modelConfig.meta || typeof modelConfig.meta !== 'object') modelConfig.meta = { modality: {} }
  if (value !== undefined && value !== null) modelConfig.meta.context_window = value
  else delete modelConfig.meta.context_window
}

function openModalityDialog(providerId: string, alias: string, modelConfig: LLMModelConfig) {
  modalityDialogTarget.value = { providerId, alias, modelConfig }
  const meta = modelConfig.meta || {}
  modalityImageParams.value = JSON.stringify((meta.modality as any)?.image ?? {}, null, 2)
  modalityVideoParams.value = JSON.stringify((meta.modality as any)?.video ?? {}, null, 2)
  modalityAudioParams.value = JSON.stringify((meta.modality as any)?.audio ?? {}, null, 2)
  modalityDialogVisible.value = true
}

function parseModalityParams(raw: string, label: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(raw || '{}')
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      showToast(`${label}参数必须是 JSON 对象`, 'error')
      return null
    }
    return parsed as Record<string, unknown>
  } catch {
    showToast(`${label}参数不是合法 JSON`, 'error')
    return null
  }
}

function confirmModalityDialog() {
  const target = modalityDialogTarget.value
  if (!target) return
  const imageParams = parseModalityParams(modalityImageParams.value, '图片')
  if (imageParams === null) return
  const videoParams = parseModalityParams(modalityVideoParams.value, '视频')
  if (videoParams === null) return
  const audioParams = parseModalityParams(modalityAudioParams.value, '音频')
  if (audioParams === null) return
  const modelConfig = target.modelConfig
  if (!modelConfig.meta) modelConfig.meta = {}
  if (!modelConfig.meta.modality) modelConfig.meta.modality = {}
  const modality = modelConfig.meta.modality as Record<string, unknown>
  if ('image' in modality) modality.image = imageParams
  if ('video' in modality) modality.video = videoParams
  if ('audio' in modality) modality.audio = audioParams
  modalityDialogVisible.value = false
  showToast(`已更新模型 "${target.alias}" 的多模态参数`, 'success', 2000)
}

// ==================== Extra params ("more parameters") ====================
const EXTRA_PARAM_EXCLUDED = new Set(['model', 'max_tokens', 'extra_body', 'meta'])
const expandedParams = ref<Record<string, boolean>>({})
const jsonEditErrors = ref<Record<string, boolean>>({})
const inputDrafts = ref<Record<string, string>>({})

const modelCellKey = (providerId: string, alias: string, field = '') =>
  `${providerId}::${alias}${field ? `::${field}` : ''}`

const isParamsExpanded = (providerId: string, alias: string): boolean =>
  Boolean(expandedParams.value[modelCellKey(providerId, alias)])

function toggleParamsExpanded(providerId: string, alias: string) {
  const key = modelCellKey(providerId, alias)
  expandedParams.value[key] = !expandedParams.value[key]
}

const extraParamKeys = (modelConfig: LLMModelConfig): string[] =>
  Object.keys(modelConfig).filter((k) => !EXTRA_PARAM_EXCLUDED.has(k))

type ParamValueType = 'boolean' | 'number' | 'string' | 'json'
const paramValueType = (value: unknown): ParamValueType => {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'string') return 'string'
  return 'json'
}

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

function renameExtraParam(
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  oldKey: string,
  newKeyRaw: string | number
): boolean {
  const newKey = String(newKeyRaw).trim()
  if (!newKey || newKey === oldKey) return false
  if (EXTRA_PARAM_EXCLUDED.has(newKey)) {
    showToast(`参数名 "${newKey}" 为保留字段`, 'error')
    return false
  }
  if (newKey in modelConfig) {
    showToast(`参数名 "${newKey}" 已存在`, 'error')
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

function commitExtraParamKey(
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  oldKey: string,
  newKeyRaw: string | number
) {
  const draftKey = modelCellKey(providerId, alias, `key:${oldKey}`)
  const ok = renameExtraParam(providerId, alias, modelConfig, oldKey, newKeyRaw)
  clearDraft(draftKey)
  if (ok) {
    const valDraftKey = modelCellKey(providerId, alias, `val:${oldKey}`)
    if (valDraftKey in inputDrafts.value) {
      inputDrafts.value[modelCellKey(providerId, alias, `val:${String(newKeyRaw).trim()}`)] =
        inputDrafts.value[valDraftKey]
      clearDraft(valDraftKey)
    }
  }
}

function removeExtraParam(modelConfig: LLMModelConfig, key: string) {
  delete modelConfig[key]
}

function setNumberParam(
  _providerId: string,
  _alias: string,
  modelConfig: LLMModelConfig,
  key: string,
  value: number | undefined
) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    delete modelConfig[key]
    showToast(`已移除参数 "${key}"`, 'success', 2000)
    return
  }
  modelConfig[key] = value
}

function setStringParam(
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  key: string,
  raw: string | number
) {
  const text = String(raw).trim()
  if (!text) {
    modelConfig[key] = ''
    clearDraft(modelCellKey(providerId, alias, `val:${key}`))
    return
  }
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed !== 'string') {
      modelConfig[key] = parsed
      clearDraft(modelCellKey(providerId, alias, `val:${key}`))
      return
    }
  } catch {
    // not JSON, treat as string
  }
  modelConfig[key] = text
  clearDraft(modelCellKey(providerId, alias, `val:${key}`))
}

function openAddExtraParam(providerId: string, alias: string, modelConfig: LLMModelConfig) {
  extraParamTarget.value = { providerId, alias, modelConfig }
  newExtraParamKey.value = ''
  extraParamDialogVisible.value = true
}

function confirmAddExtraParam() {
  const target = extraParamTarget.value
  if (!target) return
  const paramName = newExtraParamKey.value.trim()
  if (!paramName) return showToast('参数名不能为空', 'error')
  if (EXTRA_PARAM_EXCLUDED.has(paramName)) return showToast(`"${paramName}" 为保留字段`, 'error')
  if (paramName in target.modelConfig) return showToast(`参数名 "${paramName}" 已存在`, 'error')
  target.modelConfig[paramName] = ''
  expandedParams.value[modelCellKey(target.providerId, target.alias)] = true
  extraParamDialogVisible.value = false
  showToast(`已添加参数 "${paramName}"`, 'success', 2000)
}

// ==================== extra_body / JSON param editing ====================
const extraBodyText = (modelConfig: LLMModelConfig): string => {
  const body = modelConfig.extra_body
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).length === 0) return ''
  return JSON.stringify(body, null, 2)
}

function applyExtraBody(providerId: string, alias: string, modelConfig: LLMModelConfig, raw: string | number) {
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
      showToast('extra_body 必须是 JSON 对象', 'error')
      return
    }
    if (Object.keys(parsed).length === 0) delete modelConfig.extra_body
    else modelConfig.extra_body = parsed as Record<string, unknown>
    clearJsonError(errKey)
    clearDraft(errKey)
  } catch {
    setJsonError(errKey)
    showToast('extra_body 不是合法 JSON', 'error')
  }
}

const jsonParamText = (value: unknown): string => JSON.stringify(value ?? null, null, 2)

function applyJsonParam(
  providerId: string,
  alias: string,
  modelConfig: LLMModelConfig,
  key: string,
  raw: string | number
) {
  const errKey = modelCellKey(providerId, alias, key)
  const text = String(raw).trim()
  if (!text) {
    setJsonError(errKey)
    showToast(`参数 "${key}" 的值不能为空`, 'error')
    return
  }
  try {
    modelConfig[key] = JSON.parse(text)
    clearJsonError(errKey)
    clearDraft(modelCellKey(providerId, alias, `val:${key}`))
  } catch {
    setJsonError(errKey)
    showToast(`参数 "${key}" 的值不是合法 JSON`, 'error')
  }
}

// ==================== Rename model alias ====================
function renameModel(providerId: string, oldAlias: string, newAliasRaw: string | number) {
  const trimmed = String(newAliasRaw).trim()
  const models = config.value[providerId]?.models
  if (!models || !trimmed || trimmed === oldAlias) {
    clearDraft(modelCellKey(providerId, oldAlias, 'alias'))
    return
  }
  if (trimmed in models) {
    showToast(`模型别名 "${trimmed}" 已存在`, 'error')
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

// ==================== Auto-save ====================
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

// 选默认提供商时自动填充该提供商的首个模型；清空提供商则清空模型（保持 provider/model 成对）
watch(
  () => llmDefault.value.provider,
  (newProvider, oldProvider) => {
    if (loading.value || newProvider === oldProvider) return
    if (!newProvider) {
      if (llmDefault.value.model) llmDefault.value.model = ''
      return
    }
    const models = config.value[newProvider]?.models || {}
    if (!llmDefault.value.model || !(llmDefault.value.model in models)) {
      const first = Object.keys(models)[0]
      if (first) llmDefault.value.model = first
      else llmDefault.value.model = ''
    }
  }
)

// 脏检测同时覆盖提供商与默认配置，任一变即触发自动保存
watch(
  [config, llmDefault],
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

// ==================== Validation & Save ====================
function validateBeforeSave(): string | null {
  for (const [providerId, provider] of Object.entries(config.value)) {
    if (!providerId.trim()) return '提供商 ID 不能为空'
    if (!provider.base_url || !provider.base_url.trim()) return `提供商 "${providerId}" 的 base_url 不能为空`
    if (typeof provider.api_key !== 'string') return `提供商 "${providerId}" 的 api_key 必须为字符串`
    const aliases = Object.keys(provider.models || {})
    if (aliases.some((a) => !a.trim())) return `提供商 "${providerId}" 存在空的模型别名`
    for (const [alias, model] of Object.entries(provider.models || {})) {
      if (!model.model || !String(model.model).trim()) return `模型 "${alias}" 的实际模型名（model）不能为空`
      if (
        model.extra_body !== undefined &&
        (typeof model.extra_body !== 'object' || model.extra_body === null || Array.isArray(model.extra_body))
      ) {
        return `模型 "${alias}" 的 extra_body 必须是 JSON 对象`
      }
    }
  }
  if (Object.keys(jsonEditErrors.value).length > 0) return '存在未通过校验的 JSON 字段，请修正后再保存'
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
    // 深度序列化为纯 JSON（含 __default__ 默认配置），避免 payload 内含 Vue 响应式 Proxy 导致 postMessage 序列化抛错
    const payload = JSON.parse(JSON.stringify(buildFullConfig()))
    postMessage({ type: 'saveLLMConfig', payload })
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

    <!-- Damaged banner (handled via empty config) -->

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
      <div style="display: flex; align-items: center; gap: 12px; font-size: 11px; color: var(--text-secondary)">
        <span v-if="loading">加载中…</span>
        <span v-else>
          <span
            :class="['status-dot', saving ? 'status-dot--saving' : dirty ? 'status-dot--dirty' : 'status-dot--clean']"
          ></span>
          {{ saving ? '保存中…' : dirty ? '有未保存修改' : '已同步' }}
          <template v-if="lastSavedAt"> · 上次保存 {{ lastSavedAt.toLocaleTimeString() }}</template>
          <template v-if="providerCount > 0"> · {{ providerCount }} 提供商 · {{ modelCount }} 模型</template>
        </span>
      </div>
      <div style="display: flex; gap: 8px">
        <button class="action-button action-button--secondary" @click="openProviderDialog">+ 添加提供商</button>
        <button class="action-button action-button--secondary" :disabled="saving" @click="reset">重置</button>
        <button class="save-button" :disabled="saving || !dirty" @click="saveNow">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <!-- 默认提供商 / 默认模型（全局，未指定 provider/model 时生效） -->
    <div
      v-if="!loading && !loadError"
      style="
        border: 1px solid var(--border-color);
        border-radius: 6px;
        padding: 12px 14px;
        margin-bottom: 12px;
      "
    >
      <div style="font-weight: 600; font-size: 12px; margin-bottom: 4px">默认提供商 / 默认模型</div>
      <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 10px">
        当会话未指定提供商 / 模型时（如 TUI「默认」）使用此默认值；留空则回退到内置 deepseek。
      </div>
      <div style="display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end">
        <div style="display: flex; flex-direction: column; gap: 4px">
          <label style="font-size: 11px; color: var(--text-secondary)">默认提供商</label>
          <select
            v-model="llmDefault.provider"
            style="
              min-width: 180px;
              padding: 4px 8px;
              border: 1px solid var(--border-color);
              border-radius: 4px;
              background: var(--bg-secondary, #1e1e1e);
              color: var(--text-primary);
              font-size: 12px;
            "
          >
            <option value="">（不设置）</option>
            <option v-for="pid in providerIds" :key="pid" :value="pid">{{ pid }}</option>
          </select>
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px">
          <label style="font-size: 11px; color: var(--text-secondary)">默认模型</label>
          <select
            v-model="llmDefault.model"
            :disabled="!llmDefault.provider"
            style="
              min-width: 180px;
              padding: 4px 8px;
              border: 1px solid var(--border-color);
              border-radius: 4px;
              background: var(--bg-secondary, #1e1e1e);
              color: var(--text-primary);
              font-size: 12px;
            "
          >
            <option v-if="!llmDefault.provider" value="" disabled>请先选择提供商</option>
            <option v-else-if="defaultModelOptions.length === 0" value="" disabled>该提供商下无可用模型</option>
            <option v-for="m in defaultModelOptions" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-state" style="padding: 40px; font-size: 15px; color: var(--text-primary)">
      ⏳ 正在加载配置…
    </div>

    <!-- Load error -->
    <div
      v-else-if="loadError"
      class="empty-state"
      style="padding: 40px; font-size: 14px; color: var(--error-fg, #e06060); text-align: center"
    >
      <p style="font-size: 28px; margin-bottom: 8px">⚠️</p>
      <p>{{ loadError }}</p>
      <button class="action-button action-button--secondary" style="margin-top: 12px" @click="loadConfig">重试</button>
    </div>

    <!-- Empty -->
    <div v-else-if="providerCount === 0" class="empty-state">
      <p>暂无 LLM 提供商配置</p>
      <p style="margin-top: 4px; font-size: 12px">点击下方按钮添加第一个提供商</p>
      <button class="save-button" style="margin-top: 12px" @click="openProviderDialog">+ 添加提供商</button>
    </div>

    <!-- Provider list -->
    <template v-else>
      <div v-for="(provider, providerId) in config" :key="providerId" class="collapsible">
        <div
          class="collapsible-header"
          @click="
            activeProviders.includes(providerId)
              ? (activeProviders = activeProviders.filter((id) => id !== providerId))
              : activeProviders.push(providerId)
          "
        >
          <span style="font-weight: 600">{{ providerId }}</span>
          <span
            style="
              font-size: 11px;
              padding: 1px 6px;
              border-radius: 3px;
              border: 1px solid var(--border-color);
              color: var(--text-secondary);
            "
          >
            {{ Object.keys(provider.models || {}).length }} 个模型
          </span>
          <span style="flex: 1"></span>
          <button class="delete-btn" title="删除提供商" @click.stop="removeProvider(providerId)">✕</button>
          <span style="font-size: 12px; color: var(--text-secondary)">{{
            activeProviders.includes(providerId) ? '▲' : '▼'
          }}</span>
        </div>

        <div v-if="activeProviders.includes(providerId)" class="collapsible-body">
          <!-- Provider fields -->
          <div class="field">
            <label class="field-label">Base URL</label>
            <input v-model="provider.base_url" class="field-input" placeholder="https://api.example.com/v1" />
          </div>
          <div class="field">
            <label class="field-label">API Key</label>
            <div style="display: flex; gap: 6px">
              <input
                v-model="provider.api_key"
                class="field-input"
                :type="showApiKey[providerId] ? 'text' : 'password'"
                placeholder="sk-..."
              />
              <button
                class="action-button action-button--secondary"
                style="padding: 6px 10px; font-size: 12px"
                @click="showApiKey[providerId] = !showApiKey[providerId]"
              >
                {{ showApiKey[providerId] ? '隐藏' : '显示' }}
              </button>
            </div>
          </div>

          <!-- Model list header -->
          <div style="display: flex; align-items: center; justify-content: space-between; margin: 12px 0 8px">
            <span class="section-title" style="margin-bottom: 0">模型列表</span>
            <button
              class="action-button action-button--secondary"
              style="padding: 4px 12px; font-size: 12px"
              @click="openModelDialog(providerId as string)"
            >
              + 添加模型
            </button>
          </div>

          <!-- Model table -->
          <div class="table-scroll">
            <table class="config-table">
              <thead>
                <tr>
                  <th>别名</th>
                  <th>模型名</th>
                  <th>Max Tokens</th>
                  <th>上下文窗口</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="(model, alias) in provider.models" :key="alias">
                  <tr>
                    <td>
                      <input
                        class="cell-input"
                        style="width: 100%; min-width: 100px"
                        :value="getDraft(modelCellKey(providerId as string, alias as string, 'alias'), alias as string)"
                        @input="
                          setDraft(
                            modelCellKey(providerId as string, alias as string, 'alias'),
                            ($event.target as HTMLInputElement).value
                          )
                        "
                        @change="
                          renameModel(providerId as string, alias as string, ($event.target as HTMLInputElement).value)
                        "
                      />
                    </td>
                    <td>
                      <input v-model="model.model" class="cell-input" style="width: 100%; min-width: 120px" />
                    </td>
                    <td>
                      <input
                        type="number"
                        class="cell-input"
                        style="width: 80px"
                        min="1"
                        :value="model.max_tokens ?? ''"
                        @change="
                          () => {
                            const v = Number(($event.target as HTMLInputElement).value)
                            if ($event.target instanceof HTMLInputElement && $event.target.value === '')
                              delete model.max_tokens
                            else if (!isNaN(v) && v > 0) model.max_tokens = v
                          }
                        "
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        class="cell-input"
                        style="width: 80px"
                        min="1"
                        :value="model.meta?.context_window ?? ''"
                        @change="
                          () => {
                            const v = Number(($event.target as HTMLInputElement).value)
                            if ($event.target instanceof HTMLInputElement && $event.target.value === '')
                              setContextWindow(model, undefined)
                            else if (!isNaN(v)) setContextWindow(model, v)
                          }
                        "
                      />
                    </td>
                    <td style="white-space: nowrap">
                      <button
                        class="delete-btn"
                        title="删除模型"
                        @click="removeModel(providerId as string, alias as string)"
                      >
                        ✕
                      </button>
                      <button
                        class="action-button action-button--secondary"
                        style="padding: 2px 8px; font-size: 11px; margin-left: 4px"
                        @click="toggleParamsExpanded(providerId as string, alias as string)"
                      >
                        {{ isParamsExpanded(providerId as string, alias as string) ? '收起' : '更多参数' }}
                      </button>
                    </td>
                  </tr>

                  <!-- Expanded: extra_body + modality + extra params -->
                  <tr v-if="isParamsExpanded(providerId as string, alias as string)">
                    <td colspan="5" style="background: var(--bg-primary); padding: 12px">
                      <!-- extra_body -->
                      <div class="field">
                        <label class="field-label">Extra Body (JSON)</label>
                        <textarea
                          class="field-textarea"
                          rows="3"
                          :class="{
                            'json-error': hasJsonError(
                              modelCellKey(providerId as string, alias as string, 'extra_body')
                            ),
                          }"
                          :value="
                            getDraft(
                              modelCellKey(providerId as string, alias as string, 'extra_body'),
                              extraBodyText(model)
                            )
                          "
                          placeholder='{"key": "value"}'
                          @input="
                            setDraft(
                              modelCellKey(providerId as string, alias as string, 'extra_body'),
                              ($event.target as HTMLTextAreaElement).value
                            )
                          "
                          @change="
                            applyExtraBody(
                              providerId as string,
                              alias as string,
                              model,
                              ($event.target as HTMLTextAreaElement).value
                            )
                          "
                        ></textarea>
                      </div>

                      <!-- Modality -->
                      <div class="field">
                        <label class="field-label">多模态能力</label>
                        <div style="display: flex; gap: 12px; flex-wrap: wrap">
                          <label
                            v-for="opt in MODALITY_OPTIONS"
                            :key="opt.key"
                            class="checkbox-row"
                            style="cursor: pointer"
                          >
                            <input
                              type="checkbox"
                              :checked="hasModality(model, opt.key)"
                              @change="toggleModality(model, opt.key, ($event.target as HTMLInputElement).checked)"
                            />
                            <span class="checkbox-label">{{ opt.label }}</span>
                          </label>
                          <button
                            v-if="
                              hasModality(model, 'image') || hasModality(model, 'video') || hasModality(model, 'audio')
                            "
                            class="action-button action-button--secondary"
                            style="padding: 2px 8px; font-size: 11px"
                            @click="openModalityDialog(providerId as string, alias as string, model)"
                          >
                            参数
                          </button>
                        </div>
                      </div>

                      <!-- Extra params -->
                      <div v-if="extraParamKeys(model).length > 0">
                        <label class="field-label" style="margin-bottom: 6px">附加参数</label>
                        <div v-for="key in extraParamKeys(model)" :key="key" style="margin-bottom: 8px">
                          <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                            <!-- Key rename -->
                            <input
                              class="cell-input"
                              style="width: 120px; font-size: 11px"
                              :value="getDraft(modelCellKey(providerId as string, alias as string, `key:${key}`), key)"
                              @input="
                                setDraft(
                                  modelCellKey(providerId as string, alias as string, `key:${key}`),
                                  ($event.target as HTMLInputElement).value
                                )
                              "
                              @change="
                                commitExtraParamKey(
                                  providerId as string,
                                  alias as string,
                                  model,
                                  key,
                                  ($event.target as HTMLInputElement).value
                                )
                              "
                            />
                            <!-- Value editor by type -->
                            <!-- boolean -->
                            <input
                              v-if="paramValueType(model[key]) === 'boolean'"
                              type="checkbox"
                              :checked="Boolean(model[key])"
                              @change="model[key] = ($event.target as HTMLInputElement).checked"
                            />
                            <!-- number -->
                            <input
                              v-else-if="paramValueType(model[key]) === 'number'"
                              type="number"
                              class="cell-input"
                              style="width: 100px; font-size: 11px"
                              :value="typeof model[key] === 'number' ? model[key] : ''"
                              @change="
                                setNumberParam(
                                  providerId as string,
                                  alias as string,
                                  model,
                                  key,
                                  Number(($event.target as HTMLInputElement).value) || undefined
                                )
                              "
                            />
                            <!-- JSON (array/object/null) -->
                            <textarea
                              v-else-if="paramValueType(model[key]) === 'json'"
                              class="field-textarea"
                              rows="2"
                              style="width: 200px; font-size: 11px"
                              :class="{
                                'json-error': hasJsonError(modelCellKey(providerId as string, alias as string, key)),
                              }"
                              :value="
                                getDraft(
                                  modelCellKey(providerId as string, alias as string, `val:${key}`),
                                  jsonParamText(model[key])
                                )
                              "
                              @input="
                                setDraft(
                                  modelCellKey(providerId as string, alias as string, `val:${key}`),
                                  ($event.target as HTMLTextAreaElement).value
                                )
                              "
                              @change="
                                applyJsonParam(
                                  providerId as string,
                                  alias as string,
                                  model,
                                  key,
                                  ($event.target as HTMLTextAreaElement).value
                                )
                              "
                            ></textarea>
                            <!-- string (auto-detects number/boolean/JSON on commit) -->
                            <input
                              v-else
                              class="cell-input"
                              style="width: 160px; font-size: 11px"
                              :value="
                                getDraft(
                                  modelCellKey(providerId as string, alias as string, `val:${key}`),
                                  String(model[key] ?? '')
                                )
                              "
                              @input="
                                setDraft(
                                  modelCellKey(providerId as string, alias as string, `val:${key}`),
                                  ($event.target as HTMLInputElement).value
                                )
                              "
                              @change="
                                setStringParam(
                                  providerId as string,
                                  alias as string,
                                  model,
                                  key,
                                  ($event.target as HTMLInputElement).value
                                )
                              "
                            />
                            <button class="delete-btn" title="删除参数" @click="removeExtraParam(model, key)">✕</button>
                          </div>
                        </div>
                      </div>

                      <button
                        class="action-button action-button--secondary"
                        style="padding: 4px 12px; font-size: 12px; margin-top: 8px"
                        @click="openAddExtraParam(providerId as string, alias as string, model)"
                      >
                        + 添加参数
                      </button>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </template>

    <!-- Add Provider Dialog -->
    <div v-if="providerDialogVisible" class="modal-overlay" @click.self="providerDialogVisible = false">
      <div class="modal">
        <div class="modal-title">添加提供商</div>
        <div class="field">
          <label class="field-label">提供商 ID</label>
          <input
            v-model="newProviderId"
            class="field-input"
            placeholder="如 openai、deepseek"
            @keyup.enter="confirmAddProvider"
          />
        </div>
        <div class="modal-actions">
          <button class="action-button action-button--secondary" @click="providerDialogVisible = false">取消</button>
          <button class="save-button" @click="confirmAddProvider">添加</button>
        </div>
      </div>
    </div>

    <!-- Add Model Dialog -->
    <div v-if="modelDialogVisible" class="modal-overlay" @click.self="modelDialogVisible = false">
      <div class="modal" style="max-width: 420px">
        <div class="modal-title">添加模型</div>
        <div class="field">
          <label class="field-label">模型别名</label>
          <input
            v-model="newModelAlias"
            class="field-input"
            placeholder="如 deepseek-chat"
            @keyup.enter="confirmAddModel"
          />
        </div>
        <div class="field">
          <label class="field-label">实际模型名</label>
          <input v-model="newModelName" class="field-input" placeholder="如 openai/deepseek-v4-flash" />
        </div>
        <div style="display: flex; gap: 12px">
          <div class="field" style="flex: 1">
            <label class="field-label">Max Tokens</label>
            <input v-model="newModelMaxTokens" type="number" class="field-input" min="1" />
          </div>
          <div class="field" style="flex: 1">
            <label class="field-label">上下文窗口</label>
            <input v-model="newModelContextWindow" type="number" class="field-input" min="1" />
          </div>
        </div>
        <div class="field">
          <label class="field-label">多模态能力</label>
          <div style="display: flex; gap: 12px; flex-wrap: wrap">
            <label v-for="opt in MODALITY_OPTIONS" :key="opt.key" class="checkbox-row" style="cursor: pointer">
              <input
                type="checkbox"
                :checked="newModelModalities.includes(opt.key)"
                @change="
                  () => {
                    if (($event.target as HTMLInputElement).checked) newModelModalities.push(opt.key)
                    else newModelModalities = newModelModalities.filter((k) => k !== opt.key)
                  }
                "
              />
              <span class="checkbox-label">{{ opt.label }}</span>
            </label>
          </div>
        </div>
        <div class="modal-actions">
          <button class="action-button action-button--secondary" @click="modelDialogVisible = false">取消</button>
          <button class="save-button" @click="confirmAddModel">添加</button>
        </div>
      </div>
    </div>

    <!-- Modality Params Dialog -->
    <div v-if="modalityDialogVisible" class="modal-overlay" @click.self="modalityDialogVisible = false">
      <div class="modal" style="max-width: 480px">
        <div class="modal-title">多模态参数 — {{ modalityDialogTarget?.alias }}</div>
        <div v-if="modalityDialogTarget && hasModality(modalityDialogTarget.modelConfig, 'image')">
          <div class="field">
            <label class="field-label">图片参数 (JSON)</label>
            <textarea v-model="modalityImageParams" class="field-textarea" rows="3"></textarea>
          </div>
        </div>
        <div v-if="modalityDialogTarget && hasModality(modalityDialogTarget.modelConfig, 'video')">
          <div class="field">
            <label class="field-label">视频参数 (JSON)</label>
            <textarea v-model="modalityVideoParams" class="field-textarea" rows="3"></textarea>
          </div>
        </div>
        <div v-if="modalityDialogTarget && hasModality(modalityDialogTarget.modelConfig, 'audio')">
          <div class="field">
            <label class="field-label">音频参数 (JSON)</label>
            <textarea v-model="modalityAudioParams" class="field-textarea" rows="3"></textarea>
          </div>
        </div>
        <div class="modal-actions">
          <button class="action-button action-button--secondary" @click="modalityDialogVisible = false">取消</button>
          <button class="save-button" @click="confirmModalityDialog">确认</button>
        </div>
      </div>
    </div>

    <!-- Add Extra Param Dialog -->
    <div v-if="extraParamDialogVisible" class="modal-overlay" @click.self="extraParamDialogVisible = false">
      <div class="modal">
        <div class="modal-title">添加参数</div>
        <div class="field">
          <label class="field-label">参数名（将透传给 LLM）</label>
          <input
            v-model="newExtraParamKey"
            class="field-input"
            placeholder="如 top_p、reasoning_effort、seed"
            @keyup.enter="confirmAddExtraParam"
          />
        </div>
        <div class="modal-actions">
          <button class="action-button action-button--secondary" @click="extraParamDialogVisible = false">取消</button>
          <button class="save-button" @click="confirmAddExtraParam">添加</button>
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
