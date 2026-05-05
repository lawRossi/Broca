<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { jobApi } from '../utils/api'
import type { Job, JobDetail, JobExecution } from '../types'

// ==================== State ====================
const jobs = ref<Job[]>([])
const loading = ref(false)
const total = ref(0)
const skip = ref(0)
const limit = ref(50)
const errorMsg = ref('')

const searchKeyword = ref('')
const statusFilter = ref('')
const typeFilter = ref('')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '活跃', value: 'active' },
  { label: '暂停', value: 'paused' },
  { label: '完成', value: 'completed' },
  { label: '取消', value: 'cancelled' },
]

const typeOptions = [
  { label: '全部类型', value: '' },
  { label: '提醒任务', value: 'reminder' },
  { label: '命令任务', value: 'command' },
]

// Detail drawer
const showDetail = ref(false)
const detailLoading = ref(false)
const jobDetail = ref<JobDetail | null>(null)
const selectedJobId = ref<string>('')
const executing = ref(false)

// ==================== Helpers ====================
const statusLabels: Record<string, string> = {
  active: '活跃',
  paused: '暂停',
  completed: '完成',
  cancelled: '取消',
}

const typeIcons: Record<string, string> = {
  reminder: '🔔',
  command: '⚡',
}

const typeLabels: Record<string, string> = {
  reminder: '提醒',
  command: '命令',
}

function getStatusClass(status: string): string {
  switch (status) {
    case 'active': return 'status-active'
    case 'paused': return 'status-paused'
    case 'completed': return 'status-completed'
    case 'cancelled': return 'status-cancelled'
    default: return ''
  }
}

function formatTrigger(job: Job): string {
  const { trigger_type, trigger_config } = job
  switch (trigger_type) {
    case 'cron':
      return `Cron: ${trigger_config.minute || '*'} ${trigger_config.hour || '*'} ${trigger_config.day || '*'} ${trigger_config.month || '*'} ${trigger_config.day_of_week || '*'}`
    case 'interval':
      const parts: string[] = []
      if (trigger_config.weeks) parts.push(`${trigger_config.weeks}周`)
      if (trigger_config.days) parts.push(`${trigger_config.days}天`)
      if (trigger_config.hours) parts.push(`${trigger_config.hours}时`)
      if (trigger_config.minutes) parts.push(`${trigger_config.minutes}分`)
      return `间隔: ${parts.join('') || '未配置'}`
    case 'date':
      return `时间: ${trigger_config.run_date || '未配置'}`
    default:
      return '未知'
  }
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '未设置'
  try {
    const d = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins}分钟前`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}小时前`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days}天前`
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return dateStr || '未知'
  }
}

function formatDateTime(dateStr?: string): string {
  if (!dateStr) return '未设置'
  try {
    return new Date(dateStr).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return dateStr
  }
}

// ==================== Actions ====================
async function fetchJobs() {
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await jobApi.getJobs({
      skip: skip.value,
      limit: limit.value,
      status: statusFilter.value || undefined,
      job_type: typeFilter.value || undefined,
      keyword: searchKeyword.value || undefined,
    })
    console.log('[JobPage] API response:', response)
    // response is already unwrapped by request()
    jobs.value = response.jobs || response || []
    total.value = response.total || (Array.isArray(response) ? response.length : jobs.value.length)
    if (Array.isArray(response)) {
      // If response is directly an array, no pagination info
      total.value = response.length
    }
  } catch (e: any) {
    console.error('[JobPage] Failed to fetch jobs:', e)
    errorMsg.value = `加载失败: ${e.message || e}`
  } finally {
    loading.value = false
  }
}

async function openDetail(jobId: string) {
  selectedJobId.value = jobId
  detailLoading.value = true
  showDetail.value = true
  try {
    const detail = await jobApi.getJobDetail(jobId)
    jobDetail.value = detail
  } catch (e: any) {
    console.error('Failed to fetch job detail:', e)
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  showDetail.value = false
  jobDetail.value = null
}

async function handleExecute(jobId: string) {
  if (!confirm('确定要立即执行此任务吗？')) return
  executing.value = true
  try {
    await jobApi.executeJob(jobId)
    await fetchJobs()
    if (selectedJobId.value === jobId) {
      await openDetail(jobId)
    }
  } catch (e: any) {
    console.error('Failed to execute job:', e)
  } finally {
    executing.value = false
  }
}

async function handlePause(jobId: string) {
  try {
    await jobApi.pauseJob(jobId)
    await fetchJobs()
    if (selectedJobId.value === jobId) {
      await openDetail(jobId)
    }
  } catch (e: any) {
    console.error('Failed to pause job:', e)
  }
}

async function handleResume(jobId: string) {
  try {
    await jobApi.resumeJob(jobId)
    await fetchJobs()
    if (selectedJobId.value === jobId) {
      await openDetail(jobId)
    }
  } catch (e: any) {
    console.error('Failed to resume job:', e)
  }
}

async function handleDelete(jobId: string) {
  if (!confirm('确定要删除这个定时任务吗？此操作不可恢复。')) return
  try {
    await jobApi.deleteJob(jobId)
    if (showDetail.value && selectedJobId.value === jobId) {
      closeDetail()
    }
    await fetchJobs()
  } catch (e: any) {
    console.error('Failed to delete job:', e)
  }
}

function onSearch() {
  skip.value = 0
  fetchJobs()
}

onMounted(() => {
  fetchJobs()
})
</script>

<template>
  <div class="job-page">
    <!-- Header -->
    <div class="page-header">
      <div class="header-left">
        <h2>⏰ 定时任务管理</h2>
        <span class="header-count">共 {{ total }} 个任务</span>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" :disabled="loading" @click="fetchJobs">🔄 刷新</button>
      </div>
    </div>

    <!-- Filters -->
    <div class="filters">
      <input
        v-model="searchKeyword"
        class="filter-input"
        placeholder="搜索任务名称、ID或内容"
        @keyup.enter="onSearch"
      />
      <select v-model="statusFilter" class="filter-select" @change="onSearch">
        <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <select v-model="typeFilter" class="filter-select" @change="onSearch">
        <option v-for="opt in typeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
    </div>

    <!-- Job List -->
    <div class="job-list">
      <div v-if="loading" class="loading-state">加载中...</div>
      <div v-else-if="errorMsg" class="error-state">{{ errorMsg }}</div>
      <div v-else-if="jobs.length === 0" class="empty-state">暂无定时任务</div>
      <div
        v-for="job in jobs"
        v-else
        :key="job.job_id"
        class="job-item"
        @click="openDetail(job.job_id)"
      >
        <div class="job-main">
          <span class="job-icon">{{ typeIcons[job.job_type] || '📋' }}</span>
          <div class="job-content">
            <div class="job-name">{{ job.name }}</div>
            <div class="job-trigger">{{ formatTrigger(job) }}</div>
          </div>
        </div>
        <div class="job-meta">
          <span class="tag" :class="getStatusClass(job.status)">{{ statusLabels[job.status] || job.status }}</span>
          <span class="job-next" :title="'下次执行: ' + formatDateTime(job.next_run_time)">
            {{ job.next_run_time ? formatDate(job.next_run_time) : '—' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Detail Drawer -->
    <div v-if="showDetail" class="drawer-overlay" @click.self="closeDetail">
      <div class="drawer">
        <div class="drawer-header">
          <h3>定时任务详情</h3>
          <button class="btn-close" @click="closeDetail">✕</button>
        </div>
        <div class="drawer-body">
          <div v-if="detailLoading" class="loading-state">加载中...</div>
          <div v-else-if="!jobDetail" class="empty-state">任务不存在</div>
          <template v-else>
            <!-- Basic info -->
            <div class="detail-section">
              <div class="detail-title-row">
                <span class="job-icon-lg">{{ typeIcons[jobDetail.job.job_type] || '📋' }}</span>
                <div>
                  <h4>{{ jobDetail.job.name }}</h4>
                  <div class="detail-tags">
                    <span class="tag" :class="getStatusClass(jobDetail.job.status)">
                      {{ statusLabels[jobDetail.job.status] }}
                    </span>
                    <span class="tag tag-type">{{ typeLabels[jobDetail.job.job_type] || jobDetail.job.job_type }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Trigger info -->
            <div class="detail-section">
              <h5>触发器配置</h5>
              <div class="info-row">
                <span class="info-label">触发器</span>
                <span class="info-value">{{ formatTrigger(jobDetail.job) }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">下次执行</span>
                <span class="info-value" :class="{ 'text-warning': jobDetail.job.next_run_time }">
                  {{ formatDateTime(jobDetail.job.next_run_time) }}
                </span>
              </div>
              <div class="info-row">
                <span class="info-label">创建时间</span>
                <span class="info-value">{{ formatDateTime(jobDetail.job.created_at) }}</span>
              </div>
              <div v-if="jobDetail.job.session_id" class="info-row">
                <span class="info-label">关联会话</span>
                <span class="info-value mono">{{ jobDetail.job.session_id }}</span>
              </div>
            </div>

            <!-- Content -->
            <div class="detail-section">
              <h5>执行内容</h5>
              <pre class="detail-pre">{{ jobDetail.job.content || '无内容' }}</pre>
            </div>

            <!-- Actions -->
            <div class="detail-section">
              <h5>操作</h5>
              <div class="action-buttons">
                <button
                  class="btn btn-primary btn-sm"
                  :disabled="jobDetail.job.status !== 'active' || executing"
                  @click="handleExecute(jobDetail.job.job_id)"
                >
                  {{ executing ? '执行中...' : '▶️ 立即执行' }}
                </button>
                <button
                  v-if="jobDetail.job.status === 'active'"
                  class="btn btn-sm"
                  style="background: rgba(245,158,11,0.15);color:#f59e0b;border-color:rgba(245,158,11,0.3)"
                  @click="handlePause(jobDetail.job.job_id)"
                >
                  ⏸️ 暂停
                </button>
                <button
                  v-if="jobDetail.job.status === 'paused'"
                  class="btn btn-sm"
                  style="background: rgba(34,197,94,0.15);color:#22c55e;border-color:rgba(34,197,94,0.3)"
                  @click="handleResume(jobDetail.job.job_id)"
                >
                  ▶️ 恢复
                </button>
                <button class="btn btn-danger btn-sm" @click="handleDelete(jobDetail.job.job_id)">🗑️ 删除</button>
              </div>
            </div>

            <!-- Execution History -->
            <div class="detail-section">
              <h5>执行历史 ({{ jobDetail.executions?.length || 0 }})</h5>
              <div v-if="!jobDetail.executions || jobDetail.executions.length === 0" class="empty-state-sm">暂无执行记录</div>
              <div v-for="exec in jobDetail.executions" :key="exec.execution_id" class="exec-item">
                <div class="exec-header">
                  <span class="tag" :class="exec.success ? 'status-completed' : 'status-blocked'">
                    {{ exec.success ? '✅ 成功' : '❌ 失败' }}
                  </span>
                  <span class="exec-time">{{ formatDateTime(exec.executed_at) }}</span>
                </div>
                <pre v-if="exec.result" class="exec-result">{{ exec.result }}</pre>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.job-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px;
  gap: 10px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h2 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-count {
  font-size: 12px;
  color: var(--text-secondary);
}

.header-actions {
  display: flex;
  gap: 6px;
}

/* ==================== Buttons ==================== */
.btn {
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.btn:hover {
  background: var(--bg-tertiary);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--button-bg);
  color: var(--button-text);
  border-color: var(--button-bg);
}

.btn-primary:hover {
  background: var(--button-hover-bg);
}

.btn-secondary {
  background: var(--bg-secondary);
}

.btn-danger {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error-fg, #ef4444);
  border-color: rgba(239, 68, 68, 0.3);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

.btn-sm {
  padding: 4px 8px;
  font-size: 11px;
}

/* ==================== Filters ==================== */
.filters {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.filter-input {
  flex: 1;
  min-width: 150px;
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 12px;
  outline: none;
}

.filter-input:focus {
  border-color: var(--focus-border);
}

.filter-select {
  background: var(--input-bg);
  color: var(--input-text);
  border: 1px solid var(--input-border);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.filter-select:focus {
  border-color: var(--focus-border);
}

/* ==================== Job List ==================== */
.job-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.job-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.job-item:hover {
  border-color: var(--focus-border);
}

.job-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.job-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.job-content {
  flex: 1;
  min-width: 0;
}

.job-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-trigger {
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: 8px;
}

.job-next {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  white-space: nowrap;
}

.tag.status-active { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.tag.status-paused { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.tag.status-completed { background: rgba(99, 102, 241, 0.15); color: #6366f1; }
.tag.status-cancelled { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.tag-type { background: rgba(59, 130, 246, 0.1); color: #3b82f6; }

/* ==================== Drawer ==================== */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: 480px;
  max-width: 90vw;
  background: var(--bg-primary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.drawer-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

.btn-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
}

.btn-close:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

/* ==================== Detail Sections ==================== */
.detail-section {
  margin-bottom: 14px;
}

.detail-section h5 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-color);
}

.detail-title-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.detail-title-row h4 {
  margin: 0 0 6px 0;
  font-size: 15px;
  color: var(--text-primary);
  word-break: break-word;
}

.job-icon-lg {
  font-size: 28px;
  flex-shrink: 0;
}

.detail-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.detail-pre {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}

.action-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 12px;
}

.info-label {
  color: var(--text-secondary);
}

.info-value {
  color: var(--text-primary);
  font-weight: 500;
}

.info-value.mono {
  font-family: var(--code-font-family, monospace);
  font-size: 11px;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.text-warning {
  color: #f59e0b;
}

/* ==================== States ==================== */
.loading-state, .empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-secondary);
  font-size: 13px;
}

.error-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--error-fg, #ef4444);
  font-size: 13px;
}

.empty-state-sm {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 8px 0;
}

/* ==================== Execution History ==================== */
.exec-item {
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  margin-bottom: 6px;
}

.exec-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.exec-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.exec-result {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
  margin: 4px 0 0;
  padding: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
}
</style>
