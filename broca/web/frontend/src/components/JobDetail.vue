<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Job, JobExecution, TriggerConfig } from '@/api/job'
import { JobStatus, JobType } from '@/api/job'
import { jobApi } from '@/api/job'
import { Loading } from '@element-plus/icons-vue'

interface Props {
  visible: boolean
  jobId?: string
}

interface Emits {
  (e: 'update:visible', value: boolean): void
  (e: 'refresh'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const jobDetail = ref<{
  job: Job
  executions: JobExecution[]
} | null>(null)
const loading = ref(false)
const executing = ref(false)
const showAllExecutions = ref(false)
const isMobile = ref(false)

const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 640
}

onMounted(() => {
  updateIsMobile()
  window.addEventListener('resize', updateIsMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateIsMobile)
})

const drawerSize = computed(() => (isMobile.value ? '100%' : '600px'))

const displayedExecutions = computed(() => {
  if (!jobDetail.value) return []
  if (showAllExecutions.value) {
    return jobDetail.value.executions
  }
  return jobDetail.value.executions.slice(0, 5)
})

const getStatusType = (status: JobStatus): string => {
  switch (status) {
    case JobStatus.ACTIVE:
      return 'success'
    case JobStatus.PAUSED:
      return 'warning'
    case JobStatus.COMPLETED:
      return 'info'
    case JobStatus.CANCELLED:
      return 'danger'
    default:
      return 'info'
  }
}

const getStatusText = (status: JobStatus): string => {
  switch (status) {
    case JobStatus.ACTIVE:
      return '活跃'
    case JobStatus.PAUSED:
      return '暂停'
    case JobStatus.COMPLETED:
      return '完成'
    case JobStatus.CANCELLED:
      return '取消'
    default:
      return '未知'
  }
}

const getJobTypeInfo = (jobType: JobType): { icon: string; text: string } => {
  switch (jobType) {
    case JobType.REMINDER:
      return { icon: '🔔', text: '提醒任务' }
    case JobType.COMMAND:
      return { icon: '⚡', text: '命令任务' }
    default:
      return { icon: '❓', text: '未知类型' }
  }
}

const formatTriggerConfig = (trigger_type: string, trigger_config: TriggerConfig): string => {
  switch (trigger_type) {
    case 'cron':
      const cronConfig = trigger_config as Record<string, any>
      return `Cron: ${cronConfig.minute || '*'} ${cronConfig.hour || '*'} ${cronConfig.day || '*'} ${cronConfig.month || '*'} ${cronConfig.day_of_week || '*'}`
    case 'interval':
      const intervalConfig = trigger_config as Record<string, any>
      const parts = []
      if (intervalConfig.weeks) parts.push(`${intervalConfig.weeks}周`)
      if (intervalConfig.days) parts.push(`${intervalConfig.days}天`)
      if (intervalConfig.hours) parts.push(`${intervalConfig.hours}小时`)
      if (intervalConfig.minutes) parts.push(`${intervalConfig.minutes}分钟`)
      if (intervalConfig.seconds) parts.push(`${intervalConfig.seconds}秒`)
      return `间隔: ${parts.join('') || '未配置'}`
    case 'date':
      const dateConfig = trigger_config as Record<string, any>
      return `时间: ${dateConfig.run_date || '未配置'}`
    default:
      return '未知触发器'
  }
}

const formatDateTime = (dateStr?: string): string => {
  if (!dateStr) return '未设置'
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return dateStr
  }
}

const loadJobDetail = async () => {
  if (!props.jobId) return
  try {
    loading.value = true
    const response = await jobApi.getJobDetail(props.jobId, 50)
    jobDetail.value = response
  } catch (error: any) {
    console.error('加载任务详情失败:', error)
    ElMessage.error('加载任务详情失败')
    jobDetail.value = null
  } finally {
    loading.value = false
  }
}

const handleExecute = async () => {
  if (!props.jobId) return
  try {
    executing.value = true
    await jobApi.executeJobNow(props.jobId)
    ElMessage.success('任务已触发执行')
    await loadJobDetail()
    emit('refresh')
  } catch (error: any) {
    console.error('执行任务失败:', error)
    ElMessage.error('执行任务失败: ' + (error.message || '未知错误'))
  } finally {
    executing.value = false
  }
}

const handlePause = async () => {
  if (!props.jobId) return
  try {
    await jobApi.pauseJob(props.jobId)
    ElMessage.success('任务已暂停')
    await loadJobDetail()
    emit('refresh')
  } catch (error: any) {
    console.error('暂停任务失败:', error)
    ElMessage.error('暂停任务失败')
  }
}

const handleResume = async () => {
  if (!props.jobId) return
  try {
    await jobApi.resumeJob(props.jobId)
    ElMessage.success('任务已恢复')
    await loadJobDetail()
    emit('refresh')
  } catch (error: any) {
    console.error('恢复任务失败:', error)
    ElMessage.error('恢复任务失败')
  }
}

const handleDelete = async () => {
  if (!props.jobId) return
  try {
    await ElMessageBox.confirm('确定要删除这个定时任务吗？此操作不可恢复。', '确认删除', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await jobApi.deleteJob(props.jobId)
    ElMessage.success('任务已删除')
    emit('refresh')
    emit('update:visible', false)
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('删除任务失败:', error)
      ElMessage.error('删除任务失败')
    }
  }
}

const handleViewExecutionResult = (execution: JobExecution) => {
  const maxHeight = isMobile.value ? '70vh' : '60vh'
  ElMessageBox.alert(
    `<pre class="result-pre" style="max-height: ${maxHeight}; overflow-y: auto;">${execution.result || '无输出'}</pre>`,
    '执行结果',
    {
      confirmButtonText: '关闭',
      dangerouslyUseHTMLString: true,
      customStyle: { width: isMobile.value ? '92%' : '600px', maxWidth: isMobile.value ? '92%' : '600px' },
    }
  )
}

watch(
  () => props.visible,
  (newVal) => {
    if (newVal && props.jobId) {
      loadJobDetail()
    } else {
      jobDetail.value = null
    }
  }
)

const handleClose = () => {
  emit('update:visible', false)
}
</script>

<template>
  <el-drawer
    :model-value="props.visible"
    title="任务详情"
    :size="drawerSize"
    :before-close="handleClose"
    @update:model-value="(val) => emit('update:visible', val)"
  >
    <div v-if="loading" class="flex items-center justify-center py-12">
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <div v-else-if="!jobDetail" class="text-center py-12 text-gray-500">
      <p>任务不存在或已被删除</p>
    </div>

    <div v-else class="space-y-4">
      <!-- 基本信息 -->
      <div class="bg-gray-50 rounded-lg p-4">
        <div class="flex items-start gap-3 mb-3">
          <span class="text-xl">{{ getJobTypeInfo(jobDetail.job.job_type).icon }}</span>
          <div class="flex-1 min-w-0">
            <h2 class="text-sm font-bold text-gray-900 break-words">
              {{ jobDetail.job.name }}
            </h2>
            <div class="flex gap-1 mt-2 flex-wrap">
              <el-tag :type="getStatusType(jobDetail.job.status)" size="small">
                {{ getStatusText(jobDetail.job.status) }}
              </el-tag>
              <el-tag size="small" type="info">
                {{ getJobTypeInfo(jobDetail.job.job_type).text }}
              </el-tag>
            </div>
          </div>
        </div>

        <div class="space-y-3">
          <div>
            <div class="text-xs font-medium text-gray-500 mb-1">
              任务ID
            </div>
            <code class="block p-2 bg-gray-100 rounded text-xs break-all">{{ jobDetail.job.job_id }}</code>
          </div>

          <div>
            <div class="text-xs font-medium text-gray-500 mb-1">
              触发器
            </div>
            <div class="p-2 bg-white rounded border text-xs text-gray-600 break-all">
              {{ formatTriggerConfig(jobDetail.job.trigger_type, jobDetail.job.trigger_config) }}
            </div>
          </div>

          <div>
            <div class="text-xs font-medium text-gray-500 mb-1">
              执行内容
            </div>
            <pre class="p-3 bg-gray-800 text-gray-100 rounded text-xs overflow-auto max-h-48 whitespace-pre-wrap">{{
              jobDetail.job.content || '无内容'
            }}</pre>
          </div>

          <div class="grid grid-cols-2 gap-2 text-xs">
            <div v-if="jobDetail.job.session_id">
              <span class="text-gray-500">关联会话</span>
              <p class="text-gray-700 break-all">
                {{ jobDetail.job.session_id }}
              </p>
            </div>
            <div v-if="jobDetail.job.agent_id">
              <span class="text-gray-500">指定Agent</span>
              <p class="text-gray-700 break-all">
                {{ jobDetail.job.agent_id }}
              </p>
            </div>
            <div>
              <span class="text-gray-500">创建时间</span>
              <p class="text-gray-700">
                {{ formatDateTime(jobDetail.job.created_at) }}
              </p>
            </div>
            <div>
              <span class="text-gray-500">下次执行</span>
              <p class="text-gray-700" :class="jobDetail.job.next_run_time ? 'text-orange-600 font-medium' : ''">
                {{ formatDateTime(jobDetail.job.next_run_time) }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex flex-wrap gap-2">
        <el-button
          type="primary"
          :loading="executing"
          :disabled="jobDetail.job.status !== JobStatus.ACTIVE"
          class="flex-1 sm:flex-none"
          @click="handleExecute"
        >
          立即执行
        </el-button>
        <el-button
          v-if="jobDetail.job.status === JobStatus.ACTIVE"
          type="warning"
          class="flex-1 sm:flex-none"
          @click="handlePause"
        >
          暂停
        </el-button>
        <el-button
          v-if="jobDetail.job.status === JobStatus.PAUSED"
          type="success"
          class="flex-1 sm:flex-none"
          @click="handleResume"
        >
          恢复
        </el-button>
        <el-button type="danger" class="flex-1 sm:flex-none" @click="handleDelete">
          删除
        </el-button>
      </div>

      <!-- 执行历史 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-base font-semibold text-gray-900">
            执行历史
          </h3>
          <el-button
            v-if="jobDetail.executions.length > 5 && !showAllExecutions"
            type="primary"
            link
            @click="showAllExecutions = true"
          >
            查看全部 ({{ jobDetail.executions.length }})
          </el-button>
        </div>

        <div v-if="displayedExecutions.length === 0" class="text-center py-8 text-gray-500">
          <p>暂无执行记录</p>
        </div>

        <div v-else>
          <!-- 桌面端表格 -->
          <div class="hidden sm:block overflow-x-auto">
            <el-table :data="displayedExecutions" stripe size="small">
              <el-table-column prop="executed_at" label="执行时间" width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.executed_at) }}
                </template>
              </el-table-column>
              <el-table-column prop="success" label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                    {{ row.success ? '成功' : '失败' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="result" label="结果摘要" min-width="200">
                <template #default="{ row }">
                  <span class="truncate block max-w-xs">{{ row.result?.substring(0, 100) || '无输出' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button v-if="row.result" type="primary" link size="small" @click="handleViewExecutionResult(row)">
                    详情
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <!-- 移动端卡片 -->
          <div class="sm:hidden space-y-2">
            <div v-for="(execution, index) in displayedExecutions" :key="index" class="bg-white border rounded-lg p-3">
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                  <el-tag :type="execution.success ? 'success' : 'danger'" size="small">
                    {{ execution.success ? '成功' : '失败' }}
                  </el-tag>
                  <span class="text-xs text-gray-500">{{ formatDateTime(execution.executed_at) }}</span>
                </div>
                <el-button
                  v-if="execution.result"
                  type="primary"
                  size="small"
                  link
                  @click="handleViewExecutionResult(execution)"
                >
                  详情
                </el-button>
              </div>
              <p class="text-xs text-gray-600 truncate">
                {{ execution.result?.substring(0, 80) || '无输出' }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
:deep(.el-drawer__body) {
  padding: 16px;
  overflow-y: auto;
}

@media (max-width: 640px) {
  :deep(.el-drawer) {
    width: 100% !important;
  }

  :deep(.el-drawer__header) {
    padding: 12px 16px;
    margin-bottom: 0;
  }

  :deep(.el-drawer__title) {
    font-size: 16px;
    font-weight: 600;
  }

  .bg-gray-50.rounded-lg {
    padding: 12px;
  }

  .text-sm.font-bold {
    font-size: 15px;
  }

  .grid.grid-cols-2 {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}

.result-pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
  padding: 16px;
  background: #1f2937;
  color: #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
}

:deep(.el-message-box__content) {
  max-height: 70vh;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
</style>
