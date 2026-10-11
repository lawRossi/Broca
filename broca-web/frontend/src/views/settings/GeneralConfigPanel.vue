<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Loading, WarningFilled } from '@element-plus/icons-vue'
import configApi, { LOG_LEVELS, type GeneralConfig, type ASRConfig, type StorageConfig } from '@/api/config'

// ==================== 状态 ====================
const loading = ref(false)
const saving = ref(false)
const config = ref<GeneralConfig>({})
const initialJson = ref<string>('{}')
/** 文件缺失或损坏：显示警示条，表单用默认值，保存将重建/修复文件 */
const damaged = ref(false)
/** 当前文件路径（只读展示；实际以 BROCA_CONFIG 环境变量解析结果为准） */
const configPath = ref('~/.broca/configs/configs.json')

// 脏状态：本地修改与初始加载/基线不一致
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)

// 自动保存状态（语义与 Settings.vue 一致）
const saveFailed = ref(false)
const autoSaveBlocked = ref(false)
const lastSavedAt = ref<Date | null>(null)
const lastSavedAtText = computed(() =>
  lastSavedAt.value ? lastSavedAt.value.toLocaleTimeString('zh-CN', { hour12: false }) : ''
)

/** 表单字段定义（保持与后端 KNOWN_GENERAL_CONFIG_FIELDS 一致） */
const FIELDS: { key: keyof GeneralConfig; label: string; placeholder: string; hint: string }[] = [
  { key: 'database_dir', label: '数据库目录', placeholder: '如 ~/.broca/data', hint: '会话、记忆等数据的存放目录' },
  { key: 'log_file', label: '日志文件', placeholder: '如 ~/.broca/logs/agent.log', hint: 'Broca 运行时日志文件路径' },
  {
    key: 'log_level',
    label: '日志级别',
    placeholder: 'INFO',
    hint: '日志输出级别（DEBUG 最详细，CRITICAL 最少）',
  },
  {
    key: 'llm_config_file',
    label: 'LLM 配置文件',
    placeholder: '如 ~/.broca/configs/llm_config.json',
    hint: 'LLM 提供商/模型配置所在文件（设置页「LLM 配置」标签页编辑该文件）',
  },
  {
    key: 'socket_server_url',
    label: 'SocketIO 服务地址',
    placeholder: 'http://localhost:6868',
    hint: 'TUI 客户端连接的 SocketIO 服务地址',
  },
  {
    key: 'api_server_url',
    label: 'API 服务地址',
    placeholder: 'http://localhost:9000',
    hint: 'TUI 客户端调用的 REST API 服务地址',
  },
]

/**
 * 执行引擎配置字段定义（configs.json 的 execution 分组，数字型）
 * 单位：无特殊标注的为「秒」
 */
const EXECUTION_FIELDS: {
  key: keyof NonNullable<GeneralConfig['execution']>
  label: string
  unit: string
  hint: string
  min: number
  step: number
}[] = [
  { key: 'step_max_errors', label: 'LLM 最大重试次数', unit: '次', hint: 'LLM 调用失败/限流时的最大重试次数', min: 1, step: 1 },
  { key: 'llm_retry_delay', label: 'LLM 重试间隔', unit: '秒', hint: '两次 LLM 重试之间的等待时间', min: 0, step: 1 },
  { key: 'tool_call_timeout', label: '工具执行超时', unit: '秒', hint: '普通工具调用超时时间（assign_task 除外）', min: 1, step: 10 },
  { key: 'assign_task_timeout', label: '任务分配超时', unit: '秒', hint: 'assign_task 工具调用超时时间', min: 1, step: 60 },
  { key: 'llm_timeout', label: 'LLM 请求超时', unit: '秒', hint: 'LLM 流式请求总超时（含外层等待）', min: 1, step: 10 },
  { key: 'llm_first_chunk_timeout', label: 'LLM 首块超时', unit: '秒', hint: '等待 LLM 返回首块内容的超时时间', min: 5, step: 5 },
  { key: 'dead_loop_window', label: '死循环判定窗口', unit: '步', hint: '最近 N 步工具调用完全相同时判定为死循环', min: 2, step: 1 },
  { key: 'message_queue_size', label: '消息队列容量', unit: '条', hint: 'Agent 消息队列最大消息数', min: 1, step: 1 },
  { key: 'permission_request_timeout', label: '权限请求超时', unit: '秒', hint: '等待用户授权/拒绝的超时时间，超时后自动拒绝。服务端消息缓存 TTL 会据此自动对齐', min: 10, step: 10 },
  { key: 'agent_query_timeout', label: '用户问答超时', unit: '秒', hint: 'ask_user 等待用户回答的超时时间，超时后返回错误。服务端消息缓存 TTL 会据此自动对齐', min: 30, step: 30 },
]

/** ASR 解码方式选项 */
const DECODING_METHODS = [
  { value: 'modified_beam_search', label: 'Modified Beam Search（推荐，准确率更高）' },
  { value: 'greedy_search', label: 'Greedy Search（更快，适合低端设备）' },
]

// ==================== ASR 配置辅助 ====================
const asrValue = (fieldKey: keyof ASRConfig): string | number | undefined => {
  const asr = config.value.asr
  return asr && typeof asr === 'object' ? asr[fieldKey] : undefined
}

const setAsrValue = (fieldKey: keyof ASRConfig, value: string | number | undefined | null) => {
  const current = config.value.asr
  const asr: ASRConfig = current ? { ...current } : {}
  if (value === undefined || value === null || value === '') {
    delete asr[fieldKey]
  } else {
    asr[fieldKey] = value as any
  }
  config.value = { ...config.value, asr }
}

// ==================== 存储配置辅助 ====================
const STORAGE_BACKENDS = [
  { value: 'cloudflare', label: 'Cloudflare R2（推荐，免费额度高，全球加速）' },
  { value: 'supabase', label: 'Supabase S3' },
]

const storageValue = (fieldKey: keyof StorageConfig): string | undefined => {
  const storage = config.value.storage
  return storage && typeof storage === 'object' ? (storage[fieldKey] as string) : undefined
}

const setStorageValue = (fieldKey: keyof StorageConfig, value: string | undefined | null) => {
  const current = config.value.storage
  const storage: StorageConfig = current ? { ...current } : {}
  if (value === undefined || value === null || value === '') {
    delete storage[fieldKey]
  } else {
    storage[fieldKey] = value as any
  }
  config.value = { ...config.value, storage }
}

// ==================== 数据加载 ====================
const loadConfig = async () => {
  loading.value = true
  try {
    const data = await configApi.getGeneralConfig()
    config.value = { ...(data || {}) }
    initialJson.value = JSON.stringify(config.value)
    damaged.value = false
  } catch {
    // 文件缺失（404）或损坏（500）：用默认值继续编辑，保存将重建/修复文件
    config.value = {}
    initialJson.value = '{}'
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
/** 保存前轻量校验，返回错误提示；通过则返回 null */
const validateBeforeSave = (): string | null => {
  const level = config.value.log_level
  if (level !== undefined && level !== '' && !(LOG_LEVELS as readonly string[]).includes(level)) {
    return `log_level 必须是 ${LOG_LEVELS.join(' / ')} 之一`
  }
  // execution 分组：数字型字段须为不小于 min 的数字
  const execution = config.value.execution
  if (execution) {
    for (const field of EXECUTION_FIELDS) {
      const value = execution[field.key]
      if (value !== undefined && value !== null && (Number.isNaN(Number(value)) || Number(value) < field.min)) {
        return `${field.label} 必须是不小于 ${field.min} 的数字`
      }
    }
  }
  // storage 分组：选择后端时必填字段校验
  const storage = config.value.storage
  if (storage?.backend === 'cloudflare') {
    for (const field of ['cloudflare_account_id', 'cloudflare_access_key_id', 'cloudflare_secret_access_key'] as const) {
      if (!storage[field]?.trim()) {
        const labels: Record<string, string> = {
          cloudflare_account_id: 'Account ID',
          cloudflare_access_key_id: 'Access Key ID',
          cloudflare_secret_access_key: 'Secret Access Key',
        }
        return `选择 Cloudflare R2 后，${labels[field]} 为必填项`
      }
    }
  } else if (storage?.backend === 'supabase') {
    for (const field of ['supabase_url', 'supabase_s3_access_key_id', 'supabase_s3_secret_access_key'] as const) {
      if (!storage[field]?.trim()) {
        const labels: Record<string, string> = {
          supabase_url: 'Project URL',
          supabase_s3_access_key_id: 'S3 Access Key ID',
          supabase_s3_secret_access_key: 'S3 Secret Access Key',
        }
        return `选择 Supabase S3 后，${labels[field]} 为必填项`
      }
    }
  }
  // 其余字段允许为空
  return null
}

const emit = defineEmits<{ (e: 'dirty-change', dirty: boolean): void }>()

/** 读取 execution 字段值（做响应式深拷贝以确保触发 dirty 检测） */
const executionValue = (fieldKey: keyof NonNullable<GeneralConfig['execution']>): number | undefined => {
  const execution = config.value.execution
  return execution && typeof execution === 'object' ? execution[fieldKey] : undefined
}

/** 写回 execution 字段值：确保 execution 对象存在后更新；空/非法值时移除该字段 */
const setExecutionValue = (
  fieldKey: keyof NonNullable<GeneralConfig['execution']>,
  value: number | undefined | null
) => {
  // 深拷贝当前 execution，确保响应式变更触发脏检测
  const current = config.value.execution
  const execution: NonNullable<GeneralConfig['execution']> = current
    ? { ...current }
    : {}
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    delete execution[fieldKey]
  } else {
    execution[fieldKey] = Number(value)
  }
  config.value = { ...config.value, execution }
}

// 当 dirty 变化时上报父组件（聚合离开保护）
watch(dirty, (val) => emit('dirty-change', val))

/** 落盘保存：成功后以「发起保存时」的内容作为新基线 */
const persistConfig = async (): Promise<boolean> => {
  const snapshot = JSON.stringify(config.value)
  saving.value = true
  try {
    await configApi.saveGeneralConfig(config.value)
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
    ElMessage.success('基础配置已保存（新配置对新启动的服务生效）')
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
        <p class="mt-1">当前表单显示默认值。填写并保存将重建/修复文件，旧文件自动备份为 <code>.bak</code>。</p>
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
        <span class="text-xs text-gray-400"
          >文件：<code class="font-mono">{{ configPath }}</code></span
        >
        <el-button size="small" :icon="Refresh" :disabled="saving" @click="reset">重置</el-button>
        <el-button size="small" type="primary" :loading="saving" :disabled="!dirty" @click="saveNow">保存</el-button>
      </div>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-12">
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <div v-else class="bg-white rounded-lg border shadow-sm overflow-hidden p-5">
      <el-form label-width="150px" label-position="left" @submit.prevent>
          <el-form-item v-for="field in FIELDS" :key="field.key" :label="field.label">
            <div class="w-full">
              <el-select
                v-if="field.key === 'log_level'"
                v-model="config.log_level"
                placeholder="选择日志级别"
                class="w-full"
              >
                <el-option v-for="level in LOG_LEVELS" :key="level" :label="level" :value="level" />
              </el-select>
              <el-input v-else v-model="config[field.key]" :placeholder="field.placeholder" />
              <p class="mt-1.5 text-xs text-gray-400">{{ field.hint }}</p>
            </div>
          </el-form-item>
        </el-form>

        <!-- 执行引擎配置（execution 分组） -->
        <div class="mt-6 border-t border-gray-100 pt-5">
          <h3 class="text-sm font-medium text-gray-700 mb-1">执行引擎配置</h3>
          <p class="text-xs text-gray-400 mb-4">LLM 重试、工具执行超时、死循环检测等运行参数（configs.json 的 execution 分组）</p>
          <el-form label-width="150px" label-position="left" @submit.prevent>
            <el-form-item v-for="field in EXECUTION_FIELDS" :key="field.key" :label="field.label">
              <div class="w-full">
                <div class="flex items-center gap-2">
                  <el-input-number
                    :model-value="executionValue(field.key)"
                    :min="field.min"
                    :step="field.step"
                    controls-position="right"
                    style="width: 180px"
                    placeholder="留空使用默认"
                    @update:model-value="(val: number | undefined) => setExecutionValue(field.key, val)"
                  />
                  <span class="text-xs text-gray-400 flex-shrink-0">{{ field.unit }}</span>
                </div>
                <p class="mt-1.5 text-xs text-gray-400">{{ field.hint }}</p>
              </div>
            </el-form-item>
          </el-form>
        </div>

        <!-- ASR 语音识别配置（asr 分组） -->
        <div class="mt-6 border-t border-gray-100 pt-5">
          <h3 class="text-sm font-medium text-gray-700 mb-1">语音识别（ASR）</h3>
          <p class="text-xs text-gray-400 mb-4">语音输入使用的 ASR 模型与解码参数（configs.json 的 asr 分组，修改后需重启后端生效）</p>
          <el-form label-width="150px" label-position="left" @submit.prevent>
            <el-form-item label="模型名称">
              <div class="w-full">
                <el-input
                  :model-value="asrValue('model_name') as string | undefined"
                  placeholder="如 sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
                  @update:model-value="(val: string) => setAsrValue('model_name', val)"
                />
                <p class="mt-1.5 text-xs text-gray-400">
                  模型目录：~/.broca/models/asr/&lt;模型名称&gt;/。留空使用默认模型。
                </p>
              </div>
            </el-form-item>
            <el-form-item label="解码方式">
              <div class="w-full">
                <el-select
                  :model-value="asrValue('decoding_method') as string | undefined"
                  placeholder="默认: modified_beam_search"
                  clearable
                  @update:model-value="(val: string) => setAsrValue('decoding_method', val)"
                >
                  <el-option
                    v-for="m in DECODING_METHODS"
                    :key="m.value"
                    :label="m.label"
                    :value="m.value"
                  />
                </el-select>
                <p class="mt-1.5 text-xs text-gray-400">
                  modified_beam_search 准确率更高但稍慢；greedy_search 速度更快。
                </p>
              </div>
            </el-form-item>
            <el-form-item label="噪声门控阈值">
              <div class="w-full">
                <div class="flex items-center gap-2">
                  <el-input-number
                    :model-value="asrValue('noise_gate_rms') as number | undefined"
                    :min="0"
                    :max="1"
                    :step="0.001"
                    :precision="4"
                    controls-position="right"
                    style="width: 180px"
                    placeholder="默认: 0.005"
                    @update:model-value="(val: number | undefined) => setAsrValue('noise_gate_rms', val)"
                  />
                  <span class="text-xs text-gray-400 flex-shrink-0">RMS</span>
                </div>
                <p class="mt-1.5 text-xs text-gray-400">
                  RMS 低于此值的帧被替换为静音（0 禁用）。默认 0.005 ≈ -46 dB，用于抑制背景噪声导致的多字。
                </p>
              </div>
            </el-form-item>
          </el-form>
        </div>

        <!-- 文件上传存储（storage 分组） -->
        <div class="mt-6 border-t border-gray-100 pt-5">
          <h3 class="text-sm font-medium text-gray-700 mb-1">文件上传存储</h3>
          <p class="text-xs text-gray-400 mb-4">
            配置文件上传的 S3 兼容存储后端（configs.json 的 storage 分组，修改后即时生效）
          </p>
          <el-form label-width="150px" label-position="left" @submit.prevent>
            <el-form-item label="存储后端">
              <div class="w-full">
                <el-select
                  :model-value="storageValue('backend')"
                  placeholder="请选择存储后端"
                  clearable
                  class="w-full"
                  @update:model-value="(val: string) => setStorageValue('backend', val)"
                >
                  <el-option
                    v-for="b in STORAGE_BACKENDS"
                    :key="b.value"
                    :label="b.label"
                    :value="b.value"
                  />
                </el-select>
                <p v-if="!storageValue('backend')" class="mt-1.5 text-xs text-amber-600">
                  请选择存储后端以启用文件上传功能
                </p>
              </div>
            </el-form-item>

            <!-- Cloudflare R2 字段 -->
            <template v-if="storageValue('backend') === 'cloudflare'">
              <el-form-item label="Account ID">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('cloudflare_account_id')"
                    placeholder="Cloudflare Account ID"
                    @update:model-value="(val: string) => setStorageValue('cloudflare_account_id', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">Cloudflare Dashboard → R2 → 概览页面查看</p>
                </div>
              </el-form-item>
              <el-form-item label="Access Key ID">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('cloudflare_access_key_id')"
                    placeholder="API Token Access Key ID"
                    @update:model-value="(val: string) => setStorageValue('cloudflare_access_key_id', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">Cloudflare Dashboard → R2 → 管理 API 令牌</p>
                </div>
              </el-form-item>
              <el-form-item label="Secret Access Key">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('cloudflare_secret_access_key')"
                    type="password"
                    show-password
                    placeholder="API Token Secret Access Key"
                    @update:model-value="(val: string) => setStorageValue('cloudflare_secret_access_key', val)"
                  />
                </div>
              </el-form-item>
              <el-form-item label="Bucket 名称">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('cloudflare_bucket') || 'upload'"
                    placeholder="upload"
                    @update:model-value="(val: string) => setStorageValue('cloudflare_bucket', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">留空默认使用 upload</p>
                </div>
              </el-form-item>
              <el-form-item label="公开访问域名">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('cloudflare_public_url')"
                    placeholder="可选，留空自动生成 https://&lt;bucket&gt;.&lt;account&gt;.r2.dev"
                    @update:model-value="(val: string) => setStorageValue('cloudflare_public_url', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">
                    自定义公开访问域名（如使用 Cloudflare 自定义域名时填写）
                  </p>
                </div>
              </el-form-item>
            </template>

            <!-- Supabase S3 字段 -->
            <template v-if="storageValue('backend') === 'supabase'">
              <el-form-item label="Project URL">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('supabase_url')"
                    placeholder="如 https://xxx.supabase.co"
                    @update:model-value="(val: string) => setStorageValue('supabase_url', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">Supabase Dashboard → Settings → API → Project URL</p>
                </div>
              </el-form-item>
              <el-form-item label="S3 Access Key ID">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('supabase_s3_access_key_id')"
                    placeholder="S3 Access Key ID"
                    @update:model-value="(val: string) => setStorageValue('supabase_s3_access_key_id', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">Supabase Dashboard → Storage → Settings → S3 Credentials</p>
                </div>
              </el-form-item>
              <el-form-item label="S3 Secret Access Key">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('supabase_s3_secret_access_key')"
                    type="password"
                    show-password
                    placeholder="S3 Secret Access Key"
                    @update:model-value="(val: string) => setStorageValue('supabase_s3_secret_access_key', val)"
                  />
                </div>
              </el-form-item>
              <el-form-item label="Bucket 名称">
                <div class="w-full">
                  <el-input
                    :model-value="storageValue('supabase_bucket') || 'upload'"
                    placeholder="upload"
                    @update:model-value="(val: string) => setStorageValue('supabase_bucket', val)"
                  />
                  <p class="mt-1.5 text-xs text-gray-400">留空默认使用 upload</p>
                </div>
              </el-form-item>
            </template>
          </el-form>
        </div>
    </div>
  </div>
</template>
