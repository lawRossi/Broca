<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores'
import { useJobStore } from '@/stores/job'
import { Bell, Refresh } from '@element-plus/icons-vue'
import type { Job } from '@/api/job'

// 导入组件
import JobList from '@/components/JobList.vue'
import JobDetail from '@/components/JobDetail.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const jobStore = useJobStore()

// 计算属性（从store获取）
const jobs = computed(() => jobStore.filteredJobs)
const loading = computed(() => jobStore.loading)
const total = computed(() => jobStore.total)
const currentPage = computed(() => jobStore.currentPage)
const pageSize = computed(() => jobStore.pageSize)
const searchKeyword = computed(() => jobStore.searchKeyword)
const statusFilter = computed(() => jobStore.statusFilter)
const jobTypeFilter = computed(() => jobStore.jobTypeFilter)
const sessionFilter = computed(() => jobStore.sessionFilter)
const selectedJobs = computed(() => jobStore.selectedJobs)
const detailDrawerVisible = computed(() => jobStore.detailDrawerVisible)
const selectedJobId = computed(() => jobStore.selectedJobId)

// 计算属性：状态和类型选项
const statusOptions = computed(() => [
  { label: '全部状态', value: '' },
  { label: '活跃', value: 'active' },
  { label: '暂停', value: 'paused' },
  { label: '完成', value: 'completed' },
  { label: '取消', value: 'cancelled' }
])

const typeOptions = computed(() => [
  { label: '全部类型', value: '' },
  { label: '提醒任务', value: 'reminder' },
  { label: '命令任务', value: 'command' }
])

// 计算属性：是否已登录
const isLoggedIn = computed(() => userStore.isLoggedIn)

// 搜索
const handleSearch = (keyword: string) => {
  jobStore.setSearchKeyword(keyword)
}

// 状态筛选
const handleStatusFilterChange = (status: string) => {
  jobStore.setStatusFilter(status as any)
}

// 类型筛选
const handleTypeFilterChange = (type: string) => {
  jobStore.setJobTypeFilter(type as any)
}

// 清除 session 筛选
const clearSessionFilter = () => {
  jobStore.setSessionFilter('')
  router.replace('/jobs')
}

// 分页
const handlePageChange = (page: number) => {
  jobStore.setPage(page)
  jobStore.fetchJobs()
}

const handleSizeChange = (size: number) => {
  jobStore.setPageSize(size)
}

// 选择任务
const handleSelect = (jobId: string) => {
  jobStore.selectJob(jobId)
}

const handleDeselect = (jobId: string) => {
  jobStore.deselectJob(jobId)
}

// 查看详情
const handleView = (job: Job) => {
  jobStore.openDetail(job.job_id)
}

// 立即执行
const handleExecute = async (job: Job) => {
  try {
    await ElMessageBox.confirm(
      `确定要立即执行任务"${job.name}"吗？`,
      '确认执行',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info',
      }
    )
    await jobStore.executeJob(job.job_id)
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('执行任务失败:', error)
    }
  }
}

// 暂停任务
const handlePause = async (job: Job) => {
  try {
    await jobStore.pauseJob(job.job_id)
  } catch (error: any) {
    console.error('暂停任务失败:', error)
  }
}

// 恢复任务
const handleResume = async (job: Job) => {
  try {
    await jobStore.resumeJob(job.job_id)
  } catch (error: any) {
    console.error('恢复任务失败:', error)
  }
}

// 删除任务
const handleDelete = async (job: Job) => {
  try {
    await jobStore.deleteJob(job.job_id)
  } catch (error: any) {
    console.error('删除任务失败:', error)
  }
}

// 监听筛选条件变化
watch(
  [searchKeyword, statusFilter, jobTypeFilter, sessionFilter],
  () => {
    // 筛选条件变化时重新加载
    jobStore.fetchJobs()
  },
  { deep: true }
)

// 监听路由参数变化
watch(
  () => route.query.session_id,
  (newSessionId) => {
    jobStore.setSessionFilter(newSessionId as string || '')
  },
  { immediate: true }
)

// 组件挂载
onMounted(async () => {
  await userStore.init()
  if (!isLoggedIn.value) {
    router.push('/auth')
    return
  }
  
  // 从路由参数中获取 session_id
  const sessionIdFromRoute = route.query.session_id as string
  if (sessionIdFromRoute) {
    jobStore.setSessionFilter(sessionIdFromRoute)
  }
  
  await jobStore.fetchJobs()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 页面标题栏 -->
    <div class="sticky top-0 z-10 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <div class="flex items-center gap-3">
            <el-icon class="text-blue-600 text-xl">
              <Bell />
            </el-icon>
            <h1 class="text-xl font-bold text-gray-900">
              定时任务管理
            </h1>
          </div>
          <div class="flex items-center gap-4">
            <div class="text-sm text-gray-500">
              共 {{ total }} 个任务
            </div>
            <el-button
              :loading="loading"
              :icon="Refresh"
              @click="jobStore.refresh()"
            >
              刷新
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
      <!-- 搜索和筛选栏 -->
      <div class="bg-white rounded-lg shadow-sm border p-4 mb-6">
        <div class="flex flex-wrap gap-4 items-center">
          <!-- 搜索框 -->
          <el-input
            v-model="searchKeyword"
            placeholder="搜索任务名称、ID或内容"
            clearable
            style="width: 300px"
            @clear="handleSearch('')"
            @keyup.enter="handleSearch(searchKeyword)"
          >
            <template #prefix>
              <el-icon><svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" /></svg></el-icon>
            </template>
          </el-input>

          <!-- 状态筛选 -->
          <el-select
            v-model="statusFilter"
            placeholder="任务状态"
            clearable
            style="width: 140px"
            @change="handleStatusFilterChange"
          >
            <el-option
              v-for="option in statusOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <!-- 类型筛选 -->
          <el-select
            v-model="jobTypeFilter"
            placeholder="任务类型"
            clearable
            style="width: 140px"
            @change="handleTypeFilterChange"
          >
            <el-option
              v-for="option in typeOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <!-- Session 筛选提示 -->
          <el-tag
            v-if="sessionFilter"
            type="info"
            closable
            class="ml-2"
            @close="clearSessionFilter"
          >
            会话: {{ sessionFilter.slice(0, 8) }}...
          </el-tag>
        </div>
      </div>

      <!-- 任务列表 -->
      <JobList
        :jobs="jobs"
        :loading="loading"
        :selected-jobs="selectedJobs"
        @select="handleSelect"
        @deselect="handleDeselect"
        @view="handleView"
        @execute="handleExecute"
        @pause="handlePause"
        @resume="handleResume"
        @delete="handleDelete"
      />

      <!-- 分页器 -->
      <div
        v-if="!loading && total > 0"
        class="mt-4 bg-white rounded-lg shadow-sm border p-4"
      >
        <el-pagination
          :current-page="currentPage"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          size="small"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <!-- 任务详情抽屉 -->
    <JobDetail
      :visible="detailDrawerVisible"
      :job-id="selectedJobId"
      @update:visible="jobStore.closeDetail()"
    />
  </div>
</template>

<style scoped>
/* 移动端优化 */
@media (max-width: 640px) {
  :deep(.el-pagination) {
    justify-content: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  :deep(.el-pagination .el-pagination__sizes) {
    margin-right: 0;
  }

  :deep(.el-pagination .el-pagination__total) {
    display: none;
  }

  .bg-white.rounded-lg.shadow-sm.border.p-4 {
    padding: 1rem;
  }

  .flex.flex-wrap.gap-4.items-center {
    gap: 0.75rem;
  }

  .el-input {
    width: 100% !important;
  }
}
</style>
