<script setup lang="ts">
import { computed } from 'vue'
import type { Job } from '@/api/job'
import { JobStatus, JobType } from '@/api/job'
import { Loading, Bell, VideoPlay, VideoPause, Delete } from '@element-plus/icons-vue'

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

const isAllSelected = computed(() => {
  return props.jobs.length > 0 && props.selectedJobs.length === props.jobs.length
})

const isIndeterminate = computed(() => {
  return props.selectedJobs.length > 0 && props.selectedJobs.length < props.jobs.length
})

const handleSelectAll = () => {
  if (isAllSelected.value) {
    props.jobs.forEach((job) => {
      if (props.selectedJobs.includes(job.job_id)) {
        emit('deselect', job.job_id)
      }
    })
  } else {
    props.jobs.forEach((job) => {
      if (!props.selectedJobs.includes(job.job_id)) {
        emit('select', job.job_id)
      }
    })
  }
}

const handleJobSelect = (jobId: string) => emit('select', jobId)
const handleJobDeselect = (jobId: string) => emit('deselect', jobId)
const handleView = (job: Job) => emit('view', job)
const handleExecute = (job: Job) => emit('execute', job)
const handlePause = (job: Job) => emit('pause', job)
const handleResume = (job: Job) => emit('resume', job)
const handleDelete = (job: Job) => emit('delete', job)

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
      if (intervalConfig.hours) parts.push(`${intervalConfig.hours}时`)
      if (intervalConfig.minutes) parts.push(`${intervalConfig.minutes}分`)
      return `间隔: ${parts.join('') || '未配置'}`
    case 'date':
      const dateConfig = trigger_config as Record<string, any>
      return `时间: ${dateConfig.run_date || '未配置'}`
    default:
      return '未知'
  }
}

const formatNextRunTime = (nextRunTime?: string): string => {
  if (!nextRunTime) return '未设置'
  const date = new Date(nextRunTime)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

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
      return { icon: '🔔', text: '提醒' }
    case JobType.COMMAND:
      return { icon: '⚡', text: '命令' }
    default:
      return { icon: '❓', text: '未知' }
  }
}

const getContentPreview = (content?: string): string => {
  if (!content) return '无内容'
  return content.length > 50 ? content.substring(0, 50) + '...' : content
}
</script>

<template>
  <div class="job-list">
    <!-- 批量操作栏 -->
    <div
      v-if="selectedJobs.length > 0"
      class="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 bg-white border border-blue-300 rounded-full shadow-lg px-4 py-2 flex items-center gap-3"
      style="max-width: 90%"
    >
      <el-checkbox :model-value="isAllSelected" :indeterminate="isIndeterminate" @change="handleSelectAll" />
      <span class="text-sm">已选 {{ selectedJobs.length }}</span>
      <span class="text-xs text-gray-400">批量操作暂未开放</span>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <el-icon class="is-loading" size="24">
        <Loading />
      </el-icon>
      <span class="ml-2 text-gray-500">加载中...</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="jobs.length === 0" class="flex flex-col items-center justify-center py-12 text-gray-500">
      <el-icon size="48" class="mb-4">
        <Bell />
      </el-icon>
      <p>暂无定时任务</p>
      <p class="text-sm mt-1">
        可通过Agent的cron工具创建
      </p>
    </div>

    <!-- 任务列表 -->
    <div v-else class="space-y-2 sm:space-y-3">
      <div
        v-for="job in jobs"
        :key="job.job_id"
        class="job-card bg-white rounded-lg border p-3 sm:p-4 cursor-pointer"
        :class="{ 'ring-2 ring-blue-500': selectedJobs.includes(job.job_id) }"
        @click="handleView(job)"
      >
        <div class="flex gap-2 sm:gap-3">
          <!-- 选择框 -->
          <el-checkbox
            :model-value="selectedJobs.includes(job.job_id)"
            class="mt-0.5 flex-shrink-0"
            @change="(val: boolean) => (val ? handleJobSelect(job.job_id) : handleJobDeselect(job.job_id))"
          />

          <!-- 主内容区 -->
          <div class="flex-1 min-w-0">
            <!-- 标题行 -->
            <div class="flex items-center gap-2 mb-2 flex-wrap">
              <span class="text-base sm:text-lg">{{ getJobTypeInfo(job.job_type).icon }}</span>
              <h3 class="text-sm sm:text-base font-semibold text-gray-900 truncate flex-1 min-w-0">
                {{ job.name }}
              </h3>
              <el-tag :type="getStatusType(job.status)" size="small" class="flex-shrink-0">
                {{ getStatusText(job.status) }}
              </el-tag>
            </div>

            <!-- 信息行 -->
            <div class="text-xs text-gray-600 space-y-1 mb-2">
              <div class="flex flex-wrap gap-x-2 gap-y-0.5">
                <span class="font-medium">触发:</span>
                <span class="truncate">{{ formatTrigger(job) }}</span>
              </div>
              <div class="flex flex-wrap gap-x-2 gap-y-0.5">
                <span class="font-medium">下次:</span>
                <span :class="job.next_run_time ? 'text-orange-600' : 'text-gray-400'">
                  {{ formatNextRunTime(job.next_run_time) }}
                </span>
              </div>
            </div>

            <!-- 内容预览 -->
            <div class="text-xs text-gray-500 truncate mb-2">
              {{ getContentPreview(job.content) }}
            </div>

            <!-- 底部信息 -->
            <div class="flex items-center justify-between">
              <div class="text-xs text-gray-400">
                {{ new Date(job.created_at).toLocaleString('zh-CN') }}
              </div>

              <!-- 操作按钮 -->
              <div class="flex items-center gap-1" @click.stop>
                <el-button
                  size="small"
                  type="primary"
                  circle
                  :disabled="job.status !== JobStatus.ACTIVE"
                  @click="handleExecute(job)"
                >
                  <el-icon size="12">
                    <VideoPlay />
                  </el-icon>
                </el-button>
                <el-button
                  v-if="job.status === JobStatus.ACTIVE"
                  size="small"
                  type="warning"
                  circle
                  @click="handlePause(job)"
                >
                  <el-icon size="12">
                    <VideoPause />
                  </el-icon>
                </el-button>
                <el-button
                  v-if="job.status === JobStatus.PAUSED"
                  size="small"
                  type="success"
                  circle
                  @click="handleResume(job)"
                >
                  <el-icon size="12">
                    <VideoPlay />
                  </el-icon>
                </el-button>
                <el-button size="small" type="danger" circle @click="handleDelete(job)">
                  <el-icon size="12">
                    <Delete />
                  </el-icon>
                </el-button>
              </div>
            </div>
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

@media (max-width: 640px) {
  .job-card {
    padding: 10px 12px;
  }

  .job-card h3 {
    max-width: 140px;
  }

  .job-card .el-tag {
    font-size: 10px;
    padding: 0 4px;
    height: 16px;
    line-height: 14px;
  }

  .job-card .el-button--small {
    padding: 4px;
  }

  .job-card .el-button--small .el-icon {
    font-size: 10px;
  }
}
</style>
