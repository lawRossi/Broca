<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Loading, Delete, WarningFilled, InfoFilled } from '@element-plus/icons-vue'
import configApi, { PERMISSION_VALUES, type PermissionValue, type ToolPermissionConfig } from '@/api/config'

// ==================== 状态 ====================
const loading = ref(false)
const saving = ref(false)
const config = ref<ToolPermissionConfig>({ tools: {} })
const initialJson = ref<string>('{}')
/** 文件缺失或损坏：显示警示条，保存将创建/修复文件 */
const damaged = ref(false)

// 脏状态：本地修改与初始加载/基线不一致
const dirty = computed(() => JSON.stringify(config.value) !== initialJson.value)

// 自动保存状态（语义与 Settings.vue 一致）
const saveFailed = ref(false)
const autoSaveBlocked = ref(false)
const lastSavedAt = ref<Date | null>(null)
const lastSavedAtText = computed(() =>
  lastSavedAt.value ? lastSavedAt.value.toLocaleTimeString('zh-CN', { hour12: false }) : ''
)

// 表格数据：工具名 → 权限（只读 computed，修改通过 setPermission 写回 config）
const toolRows = computed<{ name: string; permission: string }[]>(() =>
  Object.entries(config.value.tools || {}).map(([name, permission]) => ({ name, permission }))
)

// ==================== 只读说明（优先取文件内元数据） ====================
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

// ==================== 添加工具对话框 ====================
const addDialogVisible = ref(false)
const newToolName = ref('')
const newToolPermission = ref<PermissionValue>('allow')

const openAddDialog = () => {
  newToolName.value = ''
  newToolPermission.value = 'allow'
  addDialogVisible.value = true
}

const confirmAddTool = () => {
  const name = newToolName.value.trim()
  if (!name) {
    ElMessage.warning('工具名不能为空')
    return
  }
  if (name in (config.value.tools || {})) {
    ElMessage.warning(`工具 "${name}" 已存在`)
    return
  }
  if (!config.value.tools || typeof config.value.tools !== 'object') {
    config.value.tools = {}
  }
  config.value.tools[name] = newToolPermission.value
  addDialogVisible.value = false
  ElMessage.success(`已添加工具 "${name}"（保存后生效）`)
}

// ==================== 工具操作 ====================
const setPermission = (name: string, permission: PermissionValue) => {
  if (!config.value.tools || typeof config.value.tools !== 'object') {
    config.value.tools = {}
  }
  config.value.tools[name] = permission
}

const removeTool = (name: string) => {
  const tools = { ...(config.value.tools || {}) }
  delete tools[name]
  config.value.tools = tools
  ElMessage.success(`已删除工具 "${name}"（保存后生效）`)
}

// ==================== 数据加载 ====================
const loadConfig = async () => {
  loading.value = true
  try {
    const data = await configApi.getToolPermissionConfig()
    // 完整保留 _description / _permission_values 元数据 + tools
    config.value = {
      _description: data?._description,
      _permission_values: data?._permission_values,
      tools: { ...(data?.tools || {}) },
    }
    initialJson.value = JSON.stringify(config.value)
    damaged.value = false
  } catch {
    // 文件缺失（404）或损坏（500）：用空 tools 继续编辑，保存将创建/修复文件
    config.value = { tools: {} }
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

const emit = defineEmits<{ (e: 'dirty-change', dirty: boolean): void }>()

// 当 dirty 变化时上报父组件（聚合离开保护）
watch(dirty, (val) => emit('dirty-change', val))

/** 落盘保存：成功后以「发起保存时」的内容作为新基线 */
const persistConfig = async (): Promise<boolean> => {
  const snapshot = JSON.stringify(config.value)
  saving.value = true
  try {
    // 提交完整对象：元数据原样 + 修改后 tools
    await configApi.saveToolPermissionConfig(config.value)
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
    ElMessage.success('工具权限已保存（新 Session 生效）')
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
        <p class="mt-1">当前显示空列表。保存将创建新文件，或先备份损坏文件再修复。</p>
      </div>
    </div>

    <!-- 只读说明块 -->
    <div
      class="flex items-start gap-2 mb-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700"
    >
      <el-icon class="mt-0.5 flex-shrink-0"><InfoFilled /></el-icon>
      <div>
        <p>{{ descriptionText }}</p>
        <p class="mt-1">
          权限值含义：<span v-for="p in PERMISSION_VALUES" :key="p" class="mr-3"
            ><code>{{ p }}</code
            >：{{ permissionValueText(p) }}</span
          >
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
        <el-button size="small" type="primary" plain :icon="Plus" @click="openAddDialog">添加工具</el-button>
        <el-button size="small" :icon="Refresh" :disabled="saving" @click="reset">重置</el-button>
        <el-button size="small" type="primary" :loading="saving" :disabled="!dirty" @click="saveNow">保存</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <div v-else class="bg-white rounded-lg border shadow-sm overflow-hidden">
      <el-table :data="toolRows" size="small" border>
        <el-table-column label="工具名" min-width="200">
          <template #default="{ row }">
            <span class="font-mono text-sm">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="权限" min-width="240">
          <template #default="{ row }">
            <el-select
              :model-value="row.permission"
              size="small"
              style="width: 200px"
              @change="(val: PermissionValue) => setPermission(row.name, val)"
            >
              <el-option
                v-for="p in PERMISSION_VALUES"
                :key="p"
                :label="`${p}（${permissionValueText(p)}）`"
                :value="p"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" text :icon="Delete" @click="removeTool(row.name)" />
          </template>
        </el-table-column>
        <template #empty>
          <div class="text-gray-400 text-sm py-6">暂无工具配置，点击「添加工具」创建</div>
        </template>
      </el-table>
    </div>

    <!-- 添加工具对话框 -->
    <el-dialog v-model="addDialogVisible" title="添加工具" width="420px">
      <el-form label-width="90px" @submit.prevent>
        <el-form-item label="工具名" required>
          <el-input v-model="newToolName" placeholder="如 read_file、bash" @keyup.enter="confirmAddTool" />
        </el-form-item>
        <el-form-item label="权限">
          <el-select v-model="newToolPermission" class="w-full">
            <el-option
              v-for="p in PERMISSION_VALUES"
              :key="p"
              :label="`${p}（${permissionValueText(p)}）`"
              :value="p"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAddTool">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>
