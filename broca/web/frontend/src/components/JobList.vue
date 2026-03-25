<script setup lang="ts">
import { computed } from 'vue'
import type { Job } from '@/api/job'
import { JobStatus, JobType } from '@/api/job'
import { Loading, Bell, InfoFilled } from '@element-plus/icons-vue'

interface Props {
  jobs: Job[]
  loading: boolean
  selectedJobs: string[]
}

interface Emits {
  (e: 'select', jobId: string): void
  (e: 'deselect', jobId: string): void
  (e: 'view', job: Job): void
  (e: 'execute', job: Job): void
  (e: 'pause', job: Job): void
  (e: 'resume', job: Job): void
  (e: 'delete', job: Job): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 计算属性
const isAllSelected = computed(() => {
  return props.jobs.length > 0 && props.selectedJobs.length === props.jobs.length
})

const isIndeterminate = computed(() => {
  return props.selectedJobs.length > 0 && props.selectedJobs.length < props.jobs.length
})

// 全选/取消全选
const handleSelectAll = () => {
  if (isAllSelected.value) {
    // 取消全选
    props.jobs.forEach(job => {
      if (props.selectedJobs.includes(job.job_id)) {
        emit('deselect', job.job_id)
      }
    })
  } else {
    // 全选
    props.jobs.forEach(job => {
      if (!props.selectedJobs.includes(job.job_id)) {
        emit('select', job.job_id)
      }
    })
  }
}

// 单个任务选择
const handleJobSelect = (jobId: string) => {
  emit('select', jobId)
}

const handleJobDeselect = (jobId: string) => {
  emit('deselect', jobId)
}

// 操作按钮
const handleView = (job: Job) => {
  emit('view', job)
}

const handleExecute = (job: Job) => {
  emit('execute', job)
}

const handlePause = (job: Job) => {
  emit('pause', job)
}

const handleResume = (job: Job) => {
  emit('resume', job)
}

const handleDelete = (job: Job) => {
  emit('delete', job)
}

// 格式化触发器显示
const formatTrigger = (job: Job): string => {
  const { trigger_type, trigger_config } = job
  switch (trigger_type) {
    case 'cron':
      const config = trigger_config as Record<string, any>
      return `Cron: ${config.minute || '*'} ${config.hour || '*'} ${config.day || '*'} ${config.month || '*'} ${config.day_of_week || '*'}`
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
      return '未知'
  }
}

// 格式化下次执行时间
const formatNextRunTime = (nextRunTime?: string): string => {
  if (!nextRunTime) return '未设置'
  const date = new Date(nextRunTime)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

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

// 任务类型图标和文本
const getJobTypeInfo = (jobType: JobType): { icon: string; text: string } => {
  switch (jobType) {
    case JobType.REMINDER:
      return { icon: '🔔', text: '提醒' }
    case JobType.COMMAND:
      return { icon: '⚡', text: '命令' }
    default:
      return { icon: '❓', text: '未知' }
  }
}
</script>

<template>
  <div class="job-list">
    <!-- 批量操作栏 - 固定在底部 -->
    <div
      v-if="selectedJobs.length > 0"
      class="fixed bottom-6 left-1/2 transform -translate-x-1/2 z-50 bg-white border border-blue-300 rounded-full shadow-lg px-6 py-3 flex items-center gap-4 transition-all duration-300"
      style="max-width: 90%;"
    >
      <div class="flex items-center gap-3">
        <el-checkbox
          :model-value="isAllSelected"
          :indeterminate="isIndeterminate"
          @change="handleSelectAll"
        >
          <span class="text-sm font-medium">已选择 {{ selectedJobs.length }} 项</span>
        </el-checkbox>
      </div>
      <div class="text-sm text-gray-500">
        批量操作暂未开放
      </div>
    </div>

    <!-- 加载状态 -->
    <div
      v-if="loading"
      class="flex items-center justify-center py-12"
    >
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <!-- 空状态 -->
    <div
      v-else-if="jobs.length === 0"
      class="flex flex-col items-center justify-center py-12 text-gray-500"
    >
      <el-icon size="48" class="mb-4">
        <Bell />
      </el-icon>
      <p>暂无定时任务</p>
      <p class="text-sm mt-1">您可以通过Agent的cron工具创建定时任务</p>
    </div>

    <!-- 任务列表 -->
    <div
      v-else
      class="space-y-3"
    >
      <div
        v-for="job in jobs"
        :key="job.job_id"
        class="bg-white rounded-lg border p-4 hover:shadow-md transition-shadow cursor-pointer"
        :class="{ 'ring-2 ring-blue-500': selectedJobs.includes(job.job_id) }"
      >
        <div class="flex items-start gap-4">
          <!-- 选择框 -->
          <el-checkbox
            :model-value="selectedJobs.includes(job.job_id)"
            @change="(val: boolean) => val ? handleJobSelect(job.job_id) : handleJobDeselect(job.job_id)"
            class="mt-1"
          />

          <!-- 任务图标和基本信息 -->
          <div class="flex-1 min-w-0" @click="handleView(job)">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xl">{{ getJobTypeInfo(job.job_type).icon }}</span>
              <h3 class="text-base font-semibold text-gray-900 truncate">
                {{ job.name }}
              </h3>
              <el-tag
                :type="getStatusType(job.status)"
                size="small"
                class="ml-2"
              >
                {{ getStatusText(job.status) }}
              </el-tag>
              <el-tag size="small" type="info">
                {{ getJobTypeInfo(job.job_type).text }}
              </el-tag>
            </div>

            <!-- 触发器信息 -->
            <div class="text-sm text-gray-600 mb-2">
              <div class="flex items-center gap-2">
                <span class="font-medium">触发器:</span>
                <span>{{ formatTrigger(job) }}</span>
              </div>
              <div class="flex items-center gap-2 mt-1">
                <span class="font-medium">下次执行:</span>
                <span :class="{ 'text-orange-600': job.next_run_time }">
                  {{ formatNextRunTime(job.next_run_time) }}
                </span>
              </div>
            </div>

            <!-- 执行内容预览 -->
            <div class="text-sm text-gray-500 truncate">
              <span class="font-medium">内容:</span>
              {{ job.content.length > 80 ? job.content.substring(0, 80) + '...' : job.content }}
            </div>

            <!-- 创建时间 -->
            <div class="text-xs text-gray-400 mt-2">
              创建于: {{ new Date(job.created_at).toLocaleString('zh-CN') }}
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="flex items-center gap-2" @click.stop>
            <el-tooltip content="查看详情" placement="top">
              <el-button
                size="small"
                text
                @click="handleView(job)"
              >
                <el-icon><InfoFilled /></el-icon>
              </el-button>
            </el-tooltip>

            <el-tooltip content="立即执行" placement="top">
              <el-button
                size="small"
                type="primary"
                text
                :disabled="job.status !== JobStatus.ACTIVE"
                @click="handleExecute(job)"
              >
                <el-icon><svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M8 5v14l11-7z"/></svg></el-icon>
              </el-button>
            </el-tooltip>

            <el-tooltip content="暂停" placement="top" v-if="job.status === JobStatus.ACTIVE">
              <el-button
                size="small"
                type="warning"
                text
                @click="handlePause(job)"
              >
                <el-icon><svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg></el-icon>
              </el-button>
            </el-tooltip>

            <el-tooltip content="恢复" placement="top" v-if="job.status === JobStatus.PAUSED">
              <el-button
                size="small"
                type="success"
                text
                @click="handleResume(job)"
              >
                <el-icon><svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M8 5v14l11-7z"/></svg></el-icon>
              </el-button>
            </el-tooltip>

            <el-tooltip content="删除" placement="top">
              <el-button
                size="small"
                type="danger"
                text
                @click="handleDelete(job)"
              >
                <el-icon><svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.job-list {
  width: 100%;
}

/* 优化移动端显示 */
@media (max-width: 640px) {
  .job-card {
    padding: 0.75rem 1rem;
  }
  
  .job-card .flex.items-center.gap-2 {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
}
</style>
