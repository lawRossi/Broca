<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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

// 响应式数据
const jobDetail = ref<{
  job: Job
  executions: JobExecution[]
} | null>(null)
const loading = ref(false)
const executing = ref(false)
const showAllExecutions = ref(false)

// 计算属性：展示的执行历史
const displayedExecutions = computed(() => {
  if (!jobDetail.value) return []
  if (showAllExecutions.value) {
    return jobDetail.value.executions
  }
  return jobDetail.value.executions.slice(0, 5)
})

// 状态标签类型
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

// 状态标签文本
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

// 任务类型信息
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

// 格式化触发器显示
const formatTriggerConfig = (trigger_type: string, trigger_config: TriggerConfig): string => {
  switch (trigger_type) {
    case 'cron':
      const cronConfig = trigger_config as Record<string, any>
      return `Cron 表达式: ${cronConfig.minute || '*'} ${cronConfig.hour || '*'} ${cronConfig.day || '*'} ${cronConfig.month || '*'} ${cronConfig.day_of_week || '*'}`
    case 'interval':
      const intervalConfig = trigger_config as Record<string, any>
      const parts = []
      if (intervalConfig.weeks) parts.push(`${intervalConfig.weeks}周`)
      if (intervalConfig.days) parts.push(`${intervalConfig.days}天`)
      if (intervalConfig.hours) parts.push(`${intervalConfig.hours}小时`)
      if (intervalConfig.minutes) parts.push(`${intervalConfig.minutes}分钟`)
      if (intervalConfig.seconds) parts.push(`${intervalConfig.seconds}秒`)
      return `间隔时间: ${parts.join('') || '未配置'}`
    case 'date':
      const dateConfig = trigger_config as Record<string, any>
      return `执行时间: ${dateConfig.run_date || '未配置'}`
    default:
      return '未知触发器类型'
  }
}

// 格式化日期时间
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
      second: '2-digit'
    })
  } catch {
    return dateStr
  }
}

// 加载任务详情
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

// 立即执行任务
const handleExecute = async () => {
  if (!props.jobId) return

  try {
    executing.value = true
    await jobApi.executeJobNow(props.jobId)
    ElMessage.success('任务已触发执行')
    // 刷新详情
    await loadJobDetail()
    emit('refresh')
  } catch (error: any) {
    console.error('执行任务失败:', error)
    ElMessage.error('执行任务失败: ' + (error.message || '未知错误'))
  } finally {
    executing.value = false
  }
}

// 暂停任务
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

// 恢复任务
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

// 删除任务
const handleDelete = async () => {
  if (!props.jobId) return

  try {
    await ElMessageBox.confirm(
      '确定要删除这个定时任务吗？此操作不可恢复。',
      '确认删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

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

// 查看完整执行结果
const handleViewExecutionResult = (execution: JobExecution) => {
  // 这里可以使用 Dialog 或 MessageBox 展示完整结果
  ElMessageBox.alert(
    `<pre style="white-space: pre-wrap; word-wrap: break-word; max-height: 400px; overflow-y: auto;">${execution.result || '无输出'}</pre>`,
    '执行结果',
    {
      confirmButtonText: '关闭',
      dangerouslyUseHTMLString: true,
      customStyle: {
        width: '600px'
      }
    }
  )
}

// 监听显示状态
watch(() => props.visible, (newVal) => {
  if (newVal && props.jobId) {
    loadJobDetail()
  } else {
    jobDetail.value = null
  }
})

// 关闭详情
const handleClose = () => {
  emit('update:visible', false)
}
</script>

<template>
  <el-drawer
    v-model="props.visible"
    title="任务详情"
    size="600px"
    :before-close="handleClose"
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

    <div v-else class="space-y-6">
      <!-- 任务基本信息 -->
      <div class="bg-gray-50 rounded-lg p-4">
        <div class="flex items-center gap-3 mb-4">
          <span class="text-2xl">{{ getJobTypeInfo(jobDetail.job.job_type).icon }}</span>
          <div class="flex-1">
            <h2 class="text-lg font-bold text-gray-900">{{ jobDetail.job.name }}</h2>
            <div class="flex items-center gap-2 mt-1">
              <el-tag
                :type="getStatusType(jobDetail.job.status)"
                size="small"
              >
                {{ getStatusText(jobDetail.job.status) }}
              </el-tag>
              <el-tag size="small" type="info">
                {{ getJobTypeInfo(jobDetail.job.job_type).text }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 任务ID -->
        <div class="text-sm text-gray-600 mb-2">
          <span class="font-medium">任务ID:</span>
          <code class="ml-2 px-2 py-1 bg-gray-100 rounded text-xs">{{ jobDetail.job.job_id }}</code>
        </div>

        <!-- 触发器配置 -->
        <div class="mb-3">
          <div class="text-sm font-medium text-gray-700 mb-1">触发器配置</div>
          <div class="text-sm text-gray-600 bg-white p-3 rounded border">
            {{ formatTriggerConfig(jobDetail.job.trigger_type, jobDetail.job.trigger_config) }}
          </div>
        </div>

        <!-- 执行内容 -->
        <div class="mb-3">
          <div class="text-sm font-medium text-gray-700 mb-1">执行内容</div>
          <div class="text-sm text-gray-600 bg-white p-3 rounded border whitespace-pre-wrap">
            {{ jobDetail.job.content }}
          </div>
        </div>

        <!-- 关联信息 -->
        <div class="grid grid-cols-2 gap-4 text-sm">
          <div v-if="jobDetail.job.session_id">
            <span class="font-medium text-gray-700">关联会话:</span>
            <span class="ml-2 text-gray-600">{{ jobDetail.job.session_id.substring(0, 12) }}...</span>
          </div>
          <div v-if="jobDetail.job.agent_id">
            <span class="font-medium text-gray-700">指定Agent:</span>
            <span class="ml-2 text-gray-600">{{ jobDetail.job.agent_id.substring(0, 12) }}...</span>
          </div>
          <div>
            <span class="font-medium text-gray-700">创建时间:</span>
            <span class="ml-2 text-gray-600">{{ formatDateTime(jobDetail.job.created_at) }}</span>
          </div>
          <div>
            <span class="font-medium text-gray-700">更新时间:</span>
            <span class="ml-2 text-gray-600">{{ formatDateTime(jobDetail.job.updated_at) }}</span>
          </div>
          <div>
            <span class="font-medium text-gray-700">下次执行:</span>
            <span class="ml-2" :class="jobDetail.job.next_run_time ? 'text-orange-600 font-medium' : 'text-gray-600'">
              {{ formatDateTime(jobDetail.job.next_run_time) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex items-center gap-3">
        <el-button
          type="primary"
          :loading="executing"
          :disabled="jobDetail.job.status !== JobStatus.ACTIVE"
          @click="handleExecute"
        >
          立即执行
        </el-button>
        <el-button
          v-if="jobDetail.job.status === JobStatus.ACTIVE"
          type="warning"
          @click="handlePause"
        >
          暂停
        </el-button>
        <el-button
          v-if="jobDetail.job.status === JobStatus.PAUSED"
          type="success"
          @click="handleResume"
        >
          恢复
        </el-button>
        <el-button
          type="danger"
          @click="handleDelete"
        >
          删除
        </el-button>
      </div>

      <!-- 执行历史 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-base font-semibold text-gray-900">执行历史</h3>
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

        <el-table
          v-else
          :data="displayedExecutions"
          stripe
          size="small"
          :show-overflow-tooltip="true"
        >
          <el-table-column
            prop="executed_at"
            label="执行时间"
            width="180"
          >
            <template #default="{ row }">
              {{ formatDateTime(row.executed_at) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="success"
            label="状态"
            width="100"
          >
            <template #default="{ row }">
              <el-tag
                :type="row.success ? 'success' : 'danger'"
                size="small"
              >
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="result"
            label="结果摘要"
            min-width="200"
          >
            <template #default="{ row }">
              <div class="truncate">
                {{ row.result?.substring(0, 100) || '无输出' }}
                <span v-if="row.result && row.result.length > 100">...</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column
            label="操作"
            width="80"
          >
            <template #default="{ row }">
              <el-button
                v-if="row.result"
                type="primary"
                link
                size="small"
                @click="handleViewExecutionResult(row)"
              >
                查看详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
/* 自定义样式 */
:deep(.el-drawer__body) {
  padding: 20px;
}

:deep(.el-tag) {
  font-weight: 500;
}

code {
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.75rem;
}
</style>
