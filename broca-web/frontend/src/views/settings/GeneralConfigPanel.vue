<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Loading, WarningFilled } from '@element-plus/icons-vue'
import configApi, { LOG_LEVELS, type GeneralConfig } from '@/api/config'

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
  // 其余字段允许为空
  return null
}

const emit = defineEmits<{ (e: 'dirty-change', dirty: boolean): void }>()

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
    </div>
  </div>
</template>
