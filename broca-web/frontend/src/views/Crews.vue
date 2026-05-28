<script setup lang="ts">
/**
 * 编排管理页面
 * - 执行记录：查看已提交的编排执行历史和状态
 * - 已有编排：从当前 session 所在 workspace 的 crew_configs 目录读取已有的编排配置
 */
import { computed, onMounted, onUnmounted, watch, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores'
import { useCrewStore } from '@/stores/crew'
import { useSessionStore } from '@/stores/session'
import { useSocketStore } from '@/stores/socket'
import type { CrewExecution, CrewConfigFile } from '@/api/crew'
import {
  Refresh,
  Plus,
  Connection,
  FolderOpened,
  Document,
  Edit,
  Upload,
} from '@element-plus/icons-vue'

import { formatBeijingTime } from '@/utils/time'
import CrewYamlEditor from '@/components/CrewYamlEditor.vue'
import CrewProgressDag from '@/components/CrewProgressDag.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const crewStore = useCrewStore()
const sessionStore = useSessionStore()
const socketStore = useSocketStore()

// ============ Tab 切换 ============
const activeTab = ref<'executions' | 'configs'>('executions')

// ============ 执行记录相关 ============
const executions = computed(() => crewStore.executions)
const loading = computed(() => crewStore.loading)
const total = computed(() => crewStore.total)
const sessionFilter = computed(() => crewStore.sessionFilter)
const statusFilter = computed(() => crewStore.statusFilter)

const isLoggedIn = computed(() => userStore.isLoggedIn)

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '待执行', value: 'pending' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '已失败', value: 'failed' },
  { label: '已中止', value: 'aborted' },
]

const statusTypeMap: Record<string, string> = {
  pending: 'info',
  running: 'primary',
  completed: 'success',
  failed: 'danger',
  aborted: 'warning',
}

const statusLabelMap: Record<string, string> = {
  pending: '待执行',
  running: '运行中',
  completed: '已完成',
  failed: '已失败',
  aborted: '已中止',
}

const orchestratorLabel: Record<string, string> = {
  pipeline: '流水线',
  'supervisor-worker': '主管-工人',
  'round-table': '圆桌讨论',
  broadcast: '广播分发',
  consensus: '共识评估',
  composite: '组合嵌套',
}

// ============ 当前 Session 及其 Workspace ============
const currentSessionId = ref('')
const currentWorkspace = ref('')
const sessionWorkspaceLoading = ref(false)

// 从 sessionFilter 或 route query 获取当前 session_id，找到 workspace
const resolveCurrentSession = async () => {
  const sid = sessionFilter.value || (route.query.session_id as string) || ''
  if (!sid) {
    currentSessionId.value = ''
    currentWorkspace.value = ''
    return
  }
  currentSessionId.value = sid

  // 尝试从 sessionStore 中找
  const found = sessionStore.sessions.find((s: any) => s.session_id === sid)
  if (found?.workspace) {
    currentWorkspace.value = found.workspace
    crewStore.setActiveWorkspace(found.workspace)
    return
  }

  // 否则从 API 获取
  sessionWorkspaceLoading.value = true
  try {
    const { sessionApi } = await import('@/api/session')
    const session = await sessionApi.getSession(sid)
    if (session.workspace) {
      currentWorkspace.value = session.workspace
      crewStore.setActiveWorkspace(session.workspace)
    }
  } catch {
    console.warn('Failed to fetch session workspace')
    currentWorkspace.value = ''
  } finally {
    sessionWorkspaceLoading.value = false
  }
}

// 订阅会话的编排频道，接收实时进度（与 resolveCurrentSession 分离，避免早返回跳过）
let _unsubCrewEvents: (() => Promise<void>) | null = null

const subscribeCrewEvents = async () => {
  const sid = sessionFilter.value || (route.query.session_id as string) || ''
  if (!socketStore.connected || !sid) return
  try {
    // 先取消旧的订阅（如果有），再订阅新的
    if (_unsubCrewEvents) {
      await _unsubCrewEvents()
    }
    _unsubCrewEvents = await socketStore.subscribe(sid)
  } catch {
    // 订阅失败不影响功能
  }
}

onUnmounted(async () => {
  if (_unsubCrewEvents) {
    await _unsubCrewEvents()
    _unsubCrewEvents = null
  }
})

// ============ 已有编排相关 ============
const configs = computed(() => crewStore.configFiles)
const configsLoading = computed(() => crewStore.configFilesLoading)

// 当前 session 变化时重新加载 configs
watch(currentWorkspace, (newWs) => {
  if (newWs) {
    crewStore.fetchConfigFiles(newWs)
  } else {
    crewStore.configFiles = []
  }
})

// 加载配置到编辑器
const handleLoadConfig = async (cfg: CrewConfigFile) => {
  await crewStore.loadConfigIntoEditor(cfg.filename, currentWorkspace.value)
}

// 同个 session 同一时间只允许一个编排执行
const sessionExecuting = ref(false)
const executingFile = ref<string>('')

// 监听执行记录的变化，自动同步 sessionExecuting 状态（防止页面刷新后丢失锁定）
watch(
  [executions, currentSessionId],
  ([execs, sid]) => {
    if (!sid) {
      sessionExecuting.value = false
      return
    }
    // 检查当前 session 是否有正在运行的编排
    const hasRunning = execs.some(
      (e: CrewExecution) => e.session_id === sid && e.status === 'running'
    )
    sessionExecuting.value = hasRunning
  },
  { immediate: true, deep: true }
)

const handleQuickSubmit = async (cfg: CrewConfigFile) => {
  if (!currentSessionId.value) {
    ElMessageBox.alert('请先选择一个会话', '提示')
    return
  }
  if (sessionExecuting.value) {
    ElMessageBox.alert('该会话已有编排正在执行，请等待完成后再试', '提示')
    return
  }
  sessionExecuting.value = true
  executingFile.value = cfg.filename
  try {
    await crewStore.submitCrewByPath(cfg.path, currentSessionId.value)
  } catch {
    // store 已处理
  } finally {
    executingFile.value = ''
    sessionExecuting.value = false
  }
}

// 格式化文件修改时间
const formatModTime = (timestamp: number): string => {
  return formatBeijingTime(timestamp * 1000, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ============ 执行记录操作 ============
const handleViewDetail = (execution: CrewExecution) => {
  crewStore.openDetail(execution.execution_id)
}

const handleRefresh = () => {
  if (activeTab.value === 'executions') {
    crewStore.refresh()
  } else {
    crewStore.fetchConfigFiles()
  }
}

const handleOpenEditor = () => {
  crewStore.openYamlEditor()
}

const handleCloseEditor = () => {
  crewStore.closeYamlEditor()
}

const clearSessionFilter = () => {
  crewStore.setSessionFilter('')
  router.replace('/crews')
}

const formatTime = (timeStr: string): string => {
  if (!timeStr) return '-'
  return formatBeijingTime(timeStr, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const getDuration = (execution: CrewExecution): string => {
  if (!execution.completed_at || !execution.created_at) return '-'
  const start = new Date(execution.created_at).getTime()
  const end = new Date(execution.completed_at).getTime()
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

// ============ 生命周期 ============
watch(
  [sessionFilter, statusFilter],
  () => {
    crewStore.fetchExecutions()
  },
  { deep: true }
)

watch(
  () => route.query.session_id,
  async (newId) => {
    if (newId) {
      crewStore.setSessionFilter(newId as string)
    }
    await resolveCurrentSession()
    await subscribeCrewEvents()
  },
  { immediate: true }
)

onMounted(async () => {
  await userStore.init()
  if (!isLoggedIn.value) {
    router.push('/auth')
    return
  }

  const sessionIdFromRoute = route.query.session_id as string
  if (sessionIdFromRoute) {
    crewStore.setSessionFilter(sessionIdFromRoute)
  }

  // 先连接 Socket.IO，确保能订阅编排实时事件
  if (!socketStore.connected && !socketStore.connecting) {
    try {
      await socketStore.connect()
    } catch {
      // 连接失败不影响功能，只是没有实时推送
    }
  }

  await crewStore.fetchExecutions()
  await sessionStore.fetchSessions()

  // 此时 socket 已连接（或已尝试连接），订阅会话频道以接收编排实时进度
  await resolveCurrentSession()
  await subscribeCrewEvents()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 页面标题栏 -->
    <div class="sticky top-0 z-10 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-14 sm:h-16">
          <div class="flex items-center gap-2 sm:gap-3 min-w-0">
            <el-icon class="text-purple-600 text-lg sm:text-xl flex-shrink-0"><Connection /></el-icon>
            <h1 class="text-base sm:text-xl font-bold text-gray-900 truncate">编排管理</h1>
            <el-tag type="info" size="small" effect="plain" class="hidden sm:inline-flex">Multi-Agent Orchestration</el-tag>
          </div>
          <div class="flex items-center gap-2 sm:gap-3 flex-shrink-0">
            <el-button
              v-if="activeTab === 'configs'"
              type="primary"
              size="small"
              :icon="Plus"
              @click="handleOpenEditor"
            >
              <span class="hidden sm:inline">新建编排</span>
            </el-button>
            <el-button
              size="small"
              :loading="activeTab === 'executions' ? loading : configsLoading"
              :icon="Refresh"
              @click="handleRefresh"
            >
              <span class="hidden sm:inline">刷新</span>
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 切换 -->
    <div class="bg-white border-b">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <el-tabs v-model="activeTab" class="page-tabs">
          <el-tab-pane label="执行记录" name="executions" />
          <el-tab-pane label="已有编排" name="configs" />
        </el-tabs>
      </div>
    </div>

    <!-- ==================== 执行记录 Tab ==================== -->
    <div v-if="activeTab === 'executions'" class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
      <!-- 搜索和筛选栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-3 sm:p-4 mb-4 sm:mb-6">
        <div class="flex flex-wrap gap-3 items-center">
          <el-select
            v-model="crewStore.statusFilter"
            placeholder="执行状态"
            clearable
            class="w-full sm:w-[140px]"
          >
            <el-option
              v-for="opt in statusOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>

          <el-tag v-if="sessionFilter" type="info" closable size="small" @close="clearSessionFilter">
            会话: {{ sessionFilter.slice(0, 8) }}...
          </el-tag>

          <span class="text-xs sm:text-sm text-gray-400 ml-auto">共 {{ total }} 条记录</span>
        </div>
      </div>

      <!-- 编排列表 -->
      <div class="space-y-2 sm:space-y-3">
        <div
          v-for="exec in executions"
          :key="exec.execution_id"
          class="bg-white rounded-lg shadow-sm border hover:shadow-md transition-shadow cursor-pointer"
          @click="handleViewDetail(exec)"
        >
          <div class="p-3 sm:p-5">
            <!-- 头部：状态 + 名称 + 类型 + ID -->
            <div class="flex items-start justify-between gap-2">
              <div class="flex items-start gap-2 flex-1 min-w-0 flex-wrap">
                <el-tag
                  :type="statusTypeMap[exec.status] as any"
                  size="small"
                  effect="dark"
                  class="!h-5 sm:!h-6"
                >
                  {{ statusLabelMap[exec.status] || exec.status }}
                </el-tag>
                <h3 class="font-semibold text-gray-900 text-sm sm:text-base truncate max-w-full">{{ exec.crew_name }}</h3>
                <el-tag size="small" type="info" effect="plain" class="!h-5 sm:!h-6">
                  {{ orchestratorLabel[exec.orchestrator_type] || exec.orchestrator_type }}
                </el-tag>
              </div>
              <span class="text-xs text-gray-400 flex-shrink-0 hidden sm:inline">{{ exec.execution_id.slice(0, 12) }}...</span>
            </div>

            <!-- 描述 -->
            <p class="mt-1 sm:mt-2 text-xs sm:text-sm text-gray-600 line-clamp-1">{{ exec.description }}</p>

            <!-- 元信息（移动端两列布局） -->
            <div class="mt-2 sm:mt-3 grid grid-cols-2 sm:flex sm:items-center gap-1 sm:gap-4 text-xs text-gray-400">
              <span>Agent: {{ exec.agent_count }} 个</span>
              <span v-if="exec.phases_total">阶段: {{ exec.phases.length }}/{{ exec.phases_total }}</span>
              <span class="col-span-2 sm:col-auto">{{ formatTime(exec.created_at) }}</span>
              <span v-if="exec.completed_at" class="col-span-2 sm:col-auto">耗时: {{ getDuration(exec) }}</span>
            </div>

            <!-- 进度条 -->
            <div v-if="exec.phases?.length" class="mt-2 sm:mt-3">
              <el-progress
                :percentage="Math.round((exec.progress || 0) * 100)"
                :stroke-width="4"
                :status="exec.status === 'failed' ? 'exception' : exec.status === 'completed' ? 'success' : undefined"
              />
            </div>

            <!-- 操作按钮 -->
            <div class="mt-2 sm:mt-3 flex flex-wrap gap-1.5 sm:gap-2 pt-2 sm:pt-3 border-t">
              <el-button
                size="small"
                type="primary"
                plain
                class="flex-1 sm:flex-none"
                @click.stop="router.push(`/chat/${exec.session_id}?execution_id=${exec.execution_id}`)"
              >
                查看聊天日志
              </el-button>
              <el-button
                v-if="exec.status === 'running'"
                size="small"
                type="danger"
                plain
                class="flex-1 sm:flex-none"
                @click.stop="crewStore.abortExecution(exec.execution_id)"
              >
                中止
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                class="flex-1 sm:flex-none"
                @click.stop="crewStore.deleteExecution(exec.execution_id)"
              >
                删除
              </el-button>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-if="!loading && !executions.length"
          class="text-center py-12 sm:py-16 text-gray-400"
        >
          <el-icon class="text-3xl sm:text-4xl mb-3 sm:mb-4"><Connection /></el-icon>
          <p class="text-base sm:text-lg">暂无编排执行记录</p>
          <p class="mt-1 sm:mt-2 text-xs sm:text-sm">切换到「已有编排」Tab 查看已有配置，或点击「新建编排」创建新任务</p>
        </div>
      </div>
    </div>

    <!-- ==================== 已有编排 Tab ==================== -->
    <div v-if="activeTab === 'configs'" class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
      <!-- Session/Workspace 信息栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-3 sm:p-4 mb-4 sm:mb-6">
        <div class="flex flex-col sm:flex-row flex-wrap gap-2 sm:gap-4 items-start sm:items-center">
          <div class="flex items-center gap-2">
            <el-icon class="text-gray-400 flex-shrink-0"><FolderOpened /></el-icon>
            <span class="text-sm text-gray-600 font-medium">当前会话：</span>
          </div>

          <template v-if="currentSessionId">
            <el-tag type="primary" effect="plain" size="small">
              {{ currentSessionId.slice(0, 12) }}...
            </el-tag>
            <span v-if="currentWorkspace" class="text-xs sm:text-sm text-gray-500 break-all">
              工作空间: <code class="bg-gray-100 px-1 rounded text-xs">{{ currentWorkspace }}</code>
            </span>
            <span v-else class="text-xs sm:text-sm text-yellow-500">
              该会话没有关联的工作空间
            </span>
          </template>
          <template v-else>
            <span class="text-xs sm:text-sm text-yellow-500">
              请先选择一个会话（从会话列表或聊天页面进入）
            </span>
          </template>

          <span v-if="currentWorkspace" class="text-xs text-gray-400 sm:ml-auto">
            {{ configs.length }} 个配置文件
          </span>
        </div>
      </div>

      <!-- 配置文件列表 -->
      <div v-if="configsLoading || sessionWorkspaceLoading" class="text-center py-12 sm:py-16 text-gray-400">
        <el-icon class="text-3xl sm:text-4xl mb-3 sm:mb-4 is-loading"><Refresh /></el-icon>
        <p>加载中...</p>
      </div>

      <div v-else-if="!currentWorkspace" class="text-center py-12 sm:py-16 text-gray-400">
        <el-icon class="text-3xl sm:text-4xl mb-3 sm:mb-4"><FolderOpened /></el-icon>
        <p class="text-base sm:text-lg">无法读取编排配置</p>
        <p class="mt-1 sm:mt-2 text-xs sm:text-sm">当前会话没有关联的工作空间，请选择一个有 workspace 的会话</p>
      </div>

      <div v-else-if="configs.length === 0" class="text-center py-12 sm:py-16 text-gray-400">
        <el-icon class="text-3xl sm:text-4xl mb-3 sm:mb-4"><Document /></el-icon>
        <p class="text-base sm:text-lg">该工作空间下没有编排配置文件</p>
        <p class="mt-1 sm:mt-2 text-xs sm:text-sm px-4">
          请在 <code class="bg-gray-100 px-1 rounded break-all">{{ currentWorkspace }}/crew_configs/</code> 目录下创建 .yaml 文件
        </p>
      </div>

      <div v-else class="space-y-2 sm:space-y-3">
        <div
          v-for="cfg in configs"
          :key="cfg.filename"
          class="bg-white rounded-lg shadow-sm border hover:shadow-md transition-shadow"
        >
          <div class="p-3 sm:p-5">
            <div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <h3 class="font-semibold text-gray-900 text-sm sm:text-base truncate max-w-full">
                    {{ cfg.name }}
                  </h3>
                  <el-tag
                    v-if="cfg.orchestrator_type"
                    size="small"
                    type="info"
                    effect="plain"
                    class="!h-5 sm:!h-6"
                  >
                    {{ orchestratorLabel[cfg.orchestrator_type] || cfg.orchestrator_type }}
                  </el-tag>
                  <el-tag v-if="cfg.parse_error" size="small" type="danger" effect="light" class="!h-5 sm:!h-6">
                    解析失败
                  </el-tag>
                </div>

                <p class="mt-1 text-xs sm:text-sm text-gray-500 line-clamp-1">
                  {{ cfg.description || '无描述' }}
                </p>

                <div class="mt-2 flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4 text-xs text-gray-400">
                  <span class="flex items-center gap-1">
                    <el-icon size="12"><Document /></el-icon>
                    {{ cfg.filename }}
                  </span>
                  <span v-if="cfg.agent_count > 0">
                    Agent: {{ cfg.agent_count }} 个
                    <span v-if="cfg.agent_names.length" class="hidden sm:inline">({{ cfg.agent_names.join(', ') }})</span>
                  </span>
                  <span>
                    修改: {{ formatModTime(cfg.modified_time) }}
                  </span>
                </div>
              </div>

              <div class="flex items-center gap-2 flex-shrink-0">
                <el-button
                  size="small"
                  :icon="Edit"
                  type="primary"
                  plain
                  class="flex-1 sm:flex-none"
                  @click="handleLoadConfig(cfg)"
                >
                  编辑
                </el-button>
                <el-button
                  size="small"
                  :icon="Upload"
                  type="success"
                  plain
                  class="flex-1 sm:flex-none"
                  :loading="executingFile === cfg.filename"
                  :disabled="sessionExecuting && executingFile !== cfg.filename"
                  @click="handleQuickSubmit(cfg)"
                >
                  执行
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 详情抽屉 ==================== -->
    <el-drawer
      :model-value="crewStore.detailDrawerVisible"
      :title="crewStore.executionDetail?.crew_name || '编排详情'"
      size="550px"
      @close="crewStore.closeDetail()"
    >
      <template v-if="crewStore.executionDetail">
        <div class="space-y-3 sm:space-y-4">
          <!-- 基本信息（移动端两列网格） -->
          <div class="bg-gray-50 rounded-lg p-3 sm:p-4">
            <div class="grid grid-cols-2 sm:grid-cols-1 gap-2 sm:gap-3">
              <div class="text-xs sm:text-sm">
                <span class="text-gray-500 block">执行 ID</span>
                <span class="font-mono text-xs break-all">{{ crewStore.executionDetail.execution_id }}</span>
              </div>
              <div class="text-xs sm:text-sm">
                <span class="text-gray-500 block">Session</span>
                <span class="font-mono text-xs break-all">{{ crewStore.executionDetail.session_id }}</span>
              </div>
              <div class="text-xs sm:text-sm">
                <span class="text-gray-500 block">编排器</span>
                <span>{{ orchestratorLabel[crewStore.executionDetail.orchestrator_type] || crewStore.executionDetail.orchestrator_type }}</span>
              </div>
              <div class="text-xs sm:text-sm">
                <span class="text-gray-500 block">Agent 数量</span>
                <span>{{ crewStore.executionDetail.agent_count }}</span>
              </div>
            </div>
          </div>

          <!-- 进度 DAG -->
          <div class="bg-white rounded-lg border">
            <div class="px-3 sm:px-4 py-2 sm:py-3 border-b bg-gray-50 font-medium text-xs sm:text-sm text-gray-700">
              执行进度
            </div>
            <div class="p-3 sm:p-4">
              <CrewProgressDag
                :phases="crewStore.executionDetail.phases || []"
                :status="crewStore.executionDetail.status"
                :orchestrator-type="crewStore.executionDetail.orchestrator_type"
                :progress="crewStore.executionDetail.progress"
                :phases-total="crewStore.executionDetail.phases_total"
              />
            </div>
          </div>

          <!-- 执行结果 -->
          <div v-if="crewStore.executionDetail.result" class="bg-white rounded-lg border">
            <div class="px-3 sm:px-4 py-2 sm:py-3 border-b bg-gray-50 font-medium text-xs sm:text-sm text-gray-700">
              执行结果
            </div>
            <pre class="p-3 sm:p-4 text-xs text-gray-600 overflow-x-auto max-h-48 sm:max-h-64">{{ JSON.stringify(crewStore.executionDetail.result, null, 2) }}</pre>
          </div>

        </div>
      </template>

      <template v-else>
        <div class="text-center py-12 sm:py-16 text-gray-400">
          <el-icon class="text-3xl sm:text-4xl mb-3 sm:mb-4"><Refresh /></el-icon>
          <p>加载中...</p>
        </div>
      </template>
    </el-drawer>

    <!-- YAML 编辑器弹窗 -->
    <CrewYamlEditor
      v-if="crewStore.yamlEditorVisible"
      :initial-yaml="crewStore.yamlContent"
      :config-files="configs"
      :active-workspace="currentWorkspace"
      :fixed-session-id="currentSessionId"
      @close="handleCloseEditor"
      @load-config="handleLoadConfig"
    />
  </div>
</template>

<style scoped>
.line-clamp-1 {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.page-tabs {
  padding-top: 8px;
}

.page-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

/* 移动端优化（参考 Chat.vue / SessionCard.vue / JobDetail.vue） */
@media (max-width: 640px) {
  :deep(.el-drawer) {
    width: 100% !important;
  }

  :deep(.el-drawer__header) {
    padding: 10px 16px;
    margin-bottom: 0;
  }

  :deep(.el-drawer__body) {
    padding: 12px;
  }

  /* 触摸友好 */
  :deep(.el-button) {
    min-height: 36px;
    min-width: 36px;
  }

  :deep(.overflow-y-auto) {
    -webkit-overflow-scrolling: touch;
  }

  :deep(*) {
    -webkit-tap-highlight-color: transparent;
  }

  :deep(input),
  :deep(textarea),
  :deep(.el-input__inner) {
    font-size: 16px;
  }

  /* el-select 移动端撑满 */
  :deep(.el-select) {
    width: 100% !important;
  }
}
</style>
