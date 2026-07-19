<script setup lang="ts">
/**
 * Crew 进度 DAG 组件
 * 展示编排执行的阶段进度、Agent 状态
 */
import { computed } from 'vue'
import type { PhaseResult, ExecutionStatus } from '@/api/crew'
import { CircleCheck, CircleClose, Loading, Clock, Connection } from '@element-plus/icons-vue'

const props = defineProps<{
  phases: PhaseResult[]
  status: ExecutionStatus
  orchestratorType?: string
  progress?: number // 后端算好的进度（0~1）
  phasesTotal?: number // 预期总阶段数
}>()

// 阶段状态映射
const phaseStatusIcon = computed(() => (status: string) => {
  switch (status) {
    case 'completed':
      return CircleCheck
    case 'running':
      return Loading
    case 'failed':
      return CircleClose
    default:
      return Clock
  }
})

const phaseStatusClass = computed(() => (status: string) => {
  switch (status) {
    case 'completed':
      return 'text-green-500'
    case 'running':
      return 'text-blue-500 animate-spin'
    case 'failed':
      return 'text-red-500'
    default:
      return 'text-gray-400'
  }
})

const phaseBgClass = computed(() => (status: string) => {
  switch (status) {
    case 'completed':
      return 'bg-green-50 border-green-200'
    case 'running':
      return 'bg-blue-50 border-blue-200'
    case 'failed':
      return 'bg-red-50 border-red-200'
    default:
      return 'bg-gray-50 border-gray-200'
  }
})

const overallProgress = computed(() => {
  // 优先用后端算好的进度
  if (props.progress !== undefined) return Math.round(props.progress * 100)
  if (!props.phases.length) return 0
  const completed = props.phases.filter((p) => p.status === 'completed').length
  return Math.round((completed / props.phases.length) * 100)
})

const overallStatus = computed(() => {
  switch (props.status) {
    case 'completed':
      return { text: '已完成', color: 'text-green-600', icon: CircleCheck }
    case 'running':
      return { text: '运行中', color: 'text-blue-600', icon: Loading }
    case 'failed':
      return { text: '已失败', color: 'text-red-600', icon: CircleClose }
    case 'aborted':
      return { text: '已中止', color: 'text-yellow-600', icon: CircleClose }
    default:
      return { text: '待执行', color: 'text-gray-400', icon: Clock }
  }
})
</script>

<template>
  <div class="space-y-4">
    <!-- 整体进度 -->
    <div class="bg-white rounded-lg border p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <el-icon :class="overallStatus.color" class="text-lg">
            <component :is="overallStatus.icon" />
          </el-icon>
          <span class="font-medium text-gray-900">执行状态: {{ overallStatus.text }}</span>
        </div>
        <span class="text-sm text-gray-500">{{ overallProgress }}%</span>
      </div>
      <el-progress
        :percentage="overallProgress"
        :status="props.status === 'failed' ? 'exception' : props.status === 'completed' ? 'success' : undefined"
        :stroke-width="8"
      />
    </div>

    <!-- 编排器类型标签 -->
    <div v-if="orchestratorType" class="flex items-center gap-2 text-sm text-gray-500">
      <el-icon><Connection /></el-icon>
      <span>拓扑类型: {{ orchestratorType }}</span>
    </div>

    <!-- 阶段列表（DAG 视图） -->
    <div class="relative">
      <!-- 连线 -->
      <div v-if="phases.length > 1" class="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-200" />

      <!-- 阶段节点 -->
      <div v-for="(phase, index) in phases" :key="phase.name" class="relative flex gap-3 sm:gap-4 pb-4 sm:pb-6">
        <!-- 节点圆点 -->
        <div class="relative z-10 flex-shrink-0 pt-0.5">
          <div
            :class="[
              'w-4 h-4 sm:w-5 sm:h-5 rounded-full border-2 flex items-center justify-center',
              phaseBgClass(phase.status).replace('bg-', '').replace('border-', ''),
            ]"
          >
            <div
              :class="[
                'w-2 h-2 sm:w-2.5 sm:h-2.5 rounded-full',
                phase.status === 'completed'
                  ? 'bg-green-500'
                  : phase.status === 'running'
                    ? 'bg-blue-500'
                    : phase.status === 'failed'
                      ? 'bg-red-500'
                      : 'bg-gray-300',
              ]"
            />
          </div>
        </div>

        <!-- 阶段卡片 -->
        <div :class="['flex-1 rounded-lg border p-3 sm:p-4 transition-all', phaseBgClass(phase.status)]">
          <!-- 头部：名称 + 状态（移动端竖直排列） -->
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-2">
            <div class="flex items-center gap-1.5 sm:gap-2">
              <el-icon :class="phaseStatusClass(phase.status)" class="text-sm sm:text-base">
                <component :is="phaseStatusIcon(phase.status)" />
              </el-icon>
              <span class="font-medium text-gray-900 text-sm sm:text-base">{{ phase.name }}</span>
            </div>
            <el-tag
              :type="
                phase.status === 'completed'
                  ? 'success'
                  : phase.status === 'running'
                    ? 'primary'
                    : phase.status === 'failed'
                      ? 'danger'
                      : 'info'
              "
              size="small"
              class="self-start sm:self-auto"
            >
              {{ phase.status }}
            </el-tag>
          </div>

          <!-- Agent 列表 -->
          <div v-if="phase.agents.length" class="mt-1.5 sm:mt-2 flex flex-wrap gap-1">
            <el-tag
              v-for="agent in phase.agents"
              :key="agent"
              size="small"
              :type="phase.status === 'completed' ? 'success' : phase.status === 'running' ? 'primary' : 'info'"
              effect="plain"
              class="!h-5 text-[10px] sm:!h-6 sm:text-xs"
            >
              {{ agent }}
            </el-tag>
          </div>

          <!-- 错误信息 -->
          <div v-if="phase.error" class="mt-1.5 sm:mt-2 text-xs sm:text-sm text-red-600 bg-red-50 rounded p-1.5 sm:p-2">
            {{ phase.error }}
          </div>

          <!-- 阶段序号 -->
          <div class="mt-1 text-2xs sm:text-xs text-gray-400">
            步骤 {{ index + 1 }} / {{ props.phasesTotal || phases.length }}
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!phases.length" class="text-center py-8 text-gray-400">暂无阶段信息</div>
    </div>
  </div>
</template>

<style scoped>
.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 移动端极小字号 */
.text-2xs {
  font-size: 0.65rem;
}

@media (max-width: 640px) {
  :deep(.el-tag) {
    min-height: 22px;
  }

  :deep(*) {
    -webkit-tap-highlight-color: transparent;
  }
}
</style>
