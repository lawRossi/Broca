<script setup lang="ts">
/**
 * 编排管理页面
 */
import { computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores'
import { useCrewStore } from '@/stores/crew'
import { useSessionStore } from '@/stores/session'
import type { CrewExecution } from '@/api/crew'
import {
  Promotion,
  Refresh,
  Plus,
  Connection,
  View,
} from '@element-plus/icons-vue'

import CrewYamlEditor from '@/components/CrewYamlEditor.vue'
import CrewProgressDag from '@/components/CrewProgressDag.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const crewStore = useCrewStore()
const sessionStore = useSessionStore()

// 计算属性
const executions = computed(() => crewStore.executions)
const loading = computed(() => crewStore.loading)
const total = computed(() => crewStore.total)
const sessionFilter = computed(() => crewStore.sessionFilter)
const statusFilter = computed(() => crewStore.statusFilter)

// 状态选项
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '待执行', value: 'pending' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '已失败', value: 'failed' },
  { label: '已中止', value: 'aborted' },
]

const isLoggedIn = computed(() => userStore.isLoggedIn)

// 状态标签映射
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

// 编排器类型中文名
const orchestratorLabel: Record<string, string> = {
  pipeline: '流水线',
  'supervisor-worker': '主管-工人',
  'round-table': '圆桌讨论',
  broadcast: '广播分发',
  consensus: '共识评估',
  composite: '组合嵌套',
}

// 处理函数
const handleSubmit = async (yaml: string, sessionId: string) => {
  try {
    await crewStore.submitCrew(yaml, sessionId)
  } catch {
    // 已由 store 处理
  }
}

const handleViewDetail = (execution: CrewExecution) => {
  crewStore.openDetail(execution.execution_id)
}

const handleAbort = async (execution: CrewExecution) => {
  await crewStore.abortExecution(execution.execution_id)
}

const handleRefresh = () => {
  crewStore.refresh()
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

// 格式化时间
const formatTime = (timeStr: string): string => {
  if (!timeStr) return '-'
  const d = new Date(timeStr)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 获取时长
const getDuration = (execution: CrewExecution): string => {
  if (!execution.completed_at || !execution.created_at) return '-'
  const start = new Date(execution.created_at).getTime()
  const end = new Date(execution.completed_at).getTime()
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

// 监听筛选
watch(
  [sessionFilter, statusFilter],
  () => {
    crewStore.fetchExecutions()
  },
  { deep: true }
)

watch(
  () => route.query.session_id,
  (newId) => {
    if (newId) crewStore.setSessionFilter(newId as string)
  },
  { immediate: true }
)

// 初始化
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

  await crewStore.fetchExecutions()
  await sessionStore.fetchSessions()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 页面标题栏 -->
    <div class="sticky top-0 z-10 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <div class="flex items-center gap-3">
            <el-icon class="text-purple-600 text-xl"><Connection /></el-icon>
            <h1 class="text-xl font-bold text-gray-900">编排管理</h1>
            <el-tag type="info" size="small" effect="plain">Multi-Agent Orchestration</el-tag>
          </div>
          <div class="flex items-center gap-4">
            <div class="text-sm text-gray-500">共 {{ total }} 条记录</div>
            <el-button type="primary" :icon="Plus" @click="handleOpenEditor"> 新建编排 </el-button>
            <el-button :loading="loading" :icon="Refresh" @click="handleRefresh"> 刷新 </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
      <!-- 搜索和筛选栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-4 mb-6">
        <div class="flex flex-wrap gap-4 items-center">
          <el-select
            v-model="crewStore.statusFilter"
            placeholder="执行状态"
            clearable
            style="width: 140px"
          >
            <el-option
              v-for="opt in statusOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>

          <el-tag v-if="sessionFilter" type="info" closable class="ml-2" @close="clearSessionFilter">
            会话: {{ sessionFilter.slice(0, 8) }}...
          </el-tag>
        </div>
      </div>

      <!-- 编排列表 -->
      <div class="space-y-3">
        <div
          v-for="exec in executions"
          :key="exec.execution_id"
          class="bg-white rounded-lg shadow-sm border hover:shadow-md transition-shadow cursor-pointer"
          @click="handleViewDetail(exec)"
        >
          <div class="p-5">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <el-tag
                  :type="statusTypeMap[exec.status] as any"
                  size="small"
                  effect="dark"
                >
                  {{ statusLabelMap[exec.status] || exec.status }}
                </el-tag>
                <h3 class="font-semibold text-gray-900">{{ exec.crew_name }}</h3>
                <el-tag size="small" type="info" effect="plain">
                  {{ orchestratorLabel[exec.orchestrator_type] || exec.orchestrator_type }}
                </el-tag>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs text-gray-400">{{ exec.execution_id.slice(0, 12) }}...</span>
              </div>
            </div>

            <p class="mt-2 text-sm text-gray-600 line-clamp-1">{{ exec.description }}</p>

            <div class="mt-3 flex items-center justify-between text-xs text-gray-400">
              <div class="flex items-center gap-4">
                <span>Agent: {{ exec.agent_count }} 个</span>
                <span v-if="exec.phases?.length">阶段: {{ exec.phases.length }} 个</span>
              </div>
              <div class="flex items-center gap-4">
                <span>{{ formatTime(exec.created_at) }}</span>
                <span v-if="exec.completed_at">耗时: {{ getDuration(exec) }}</span>
              </div>
            </div>

            <!-- 进度条 -->
            <div v-if="exec.phases?.length" class="mt-3">
              <el-progress
                :percentage="Math.round(
                  exec.phases.filter(p => p.status === 'completed').length / exec.phases.length * 100
                )"
                :stroke-width="4"
                :status="exec.status === 'failed' ? 'exception' : exec.status === 'completed' ? 'success' : undefined"
              />
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-if="!loading && !executions.length"
          class="text-center py-16 text-gray-400"
        >
          <el-icon class="text-4xl mb-4"><Connection /></el-icon>
          <p class="text-lg">暂无编排执行记录</p>
          <p class="mt-2 text-sm">点击"新建编排"创建一个编排任务</p>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer
      :model-value="crewStore.detailDrawerVisible"
      :title="crewStore.executionDetail?.crew_name || '编排详情'"
      size="550px"
      @close="crewStore.closeDetail()"
    >
      <template v-if="crewStore.executionDetail">
        <div class="space-y-4">
          <!-- 基本信息 -->
          <div class="bg-gray-50 rounded-lg p-4 space-y-2">
            <div class="flex justify-between text-sm">
              <span class="text-gray-500">执行 ID</span>
              <span class="font-mono text-xs">{{ crewStore.executionDetail.execution_id }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-500">Session</span>
              <span class="font-mono text-xs">{{ crewStore.executionDetail.session_id }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-500">编排器</span>
              <span>{{ orchestratorLabel[crewStore.executionDetail.orchestrator_type] || crewStore.executionDetail.orchestrator_type }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-500">Agent 数量</span>
              <span>{{ crewStore.executionDetail.agent_count }}</span>
            </div>
          </div>

          <!-- 进度 DAG -->
          <div class="bg-white rounded-lg border">
            <div class="px-4 py-3 border-b bg-gray-50 font-medium text-sm text-gray-700">
              执行进度
            </div>
            <div class="p-4">
              <CrewProgressDag
                :phases="crewStore.executionDetail.phases || []"
                :status="crewStore.executionDetail.status"
                :orchestrator-type="crewStore.executionDetail.orchestrator_type"
              />
            </div>
          </div>

          <!-- 执行结果 -->
          <div v-if="crewStore.executionDetail.result" class="bg-white rounded-lg border">
            <div class="px-4 py-3 border-b bg-gray-50 font-medium text-sm text-gray-700">
              执行结果
            </div>
            <pre class="p-4 text-xs text-gray-600 overflow-x-auto max-h-64">{{ JSON.stringify(crewStore.executionDetail.result, null, 2) }}</pre>
          </div>

          <!-- 操作按钮 -->
          <div class="flex gap-2 pt-2">
            <el-button
              v-if="crewStore.executionDetail?.status === 'running'"
              type="danger"
              @click="handleAbort(crewStore.executionDetail)"
            >
              中止执行
            </el-button>
            <el-button
              type="primary"
              plain
              @click="router.push(`/chat/${crewStore.executionDetail?.session_id}`)"
            >
              查看聊天日志
            </el-button>
            <el-button @click="handleRefresh">刷新状态</el-button>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="text-center py-16 text-gray-400">
          <el-icon class="text-4xl mb-4"><Loading /></el-icon>
          <p>加载中...</p>
        </div>
      </template>
    </el-drawer>

    <!-- YAML 编辑器弹窗 -->
    <CrewYamlEditor
      v-if="crewStore.yamlEditorVisible"
      @close="handleCloseEditor"
      @submit="handleSubmit"
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

@media (max-width: 640px) {
  :deep(.el-drawer) {
    width: 100% !important;
  }
}
</style>
