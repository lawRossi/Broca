import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { jobApi, type Job, JobStatus, JobType } from '@/api/job'

export const useJobStore = defineStore('job', () => {
  // 状态
  const jobs = ref<Job[]>([])
  const loading = ref(false)
  const total = ref(0)
  const currentPage = ref(1)
  const pageSize = ref(20)

  // 筛选条件
  const searchKeyword = ref('')
  const statusFilter = ref<JobStatus | ''>('')
  const jobTypeFilter = ref<JobType | ''>('')

  // 选中的任务
  const selectedJobs = ref<string[]>([])

  // 详情相关
  const detailDrawerVisible = ref(false)
  const selectedJobId = ref<string | undefined>(undefined)
  const jobDetail = ref<{
    job: Job
    executions: any[]
  } | null>(null)
  const detailLoading = ref(false)

  // 执行状态
  const executingJobs = ref<Set<string>>(new Set())

  // 计算属性
  const isAllSelected = computed(() => {
    return jobs.value.length > 0 && selectedJobs.value.length === jobs.value.length
  })

  const isIndeterminate = computed(() => {
    return selectedJobs.value.length > 0 && selectedJobs.value.length < jobs.value.length
  })

  const filteredJobs = computed(() => {
    let result = jobs.value

    // 关键词搜索（已经在API层处理，这里可以再做一层保险）
    if (searchKeyword.value) {
      const keyword = searchKeyword.value.toLowerCase()
      result = result.filter(
        (job) =>
          job.name.toLowerCase().includes(keyword) ||
          job.job_id.toLowerCase().includes(keyword) ||
          job.content.toLowerCase().includes(keyword)
      )
    }

    return result
  })

  // Actions
  const fetchJobs = async (params?: {
    skip?: number
    limit?: number
    status?: JobStatus
    job_type?: JobType
    keyword?: string
    order_by?: string
  }) => {
    loading.value = true

    try {
      const response = await jobApi.getJobs({
        skip: params?.skip ?? (currentPage.value - 1) * pageSize.value,
        limit: params?.limit ?? pageSize.value,
        status: params?.status ?? (statusFilter.value || undefined),
        job_type: params?.job_type ?? (jobTypeFilter.value || undefined),
        keyword: params?.keyword ?? (searchKeyword.value || undefined),
        order_by: params?.order_by ?? 'created_at desc',
      })

      jobs.value = response.jobs
      total.value = response.total
      currentPage.value = params?.skip ? Math.floor(params.skip / (params.limit || pageSize.value)) + 1 : currentPage.value
    } catch (error: any) {
      console.error('获取任务列表失败:', error)
      ElMessage.error('加载任务列表失败')
      throw error
    } finally {
      loading.value = false
    }
  }

  const fetchJobDetail = async (jobId: string, executionLimit: number = 50) => {
    detailLoading.value = true

    try {
      const response = await jobApi.getJobDetail(jobId, executionLimit)
      jobDetail.value = response
      return response
    } catch (error: any) {
      console.error('获取任务详情失败:', error)
      ElMessage.error('加载任务详情失败')
      jobDetail.value = null
      throw error
    } finally {
      detailLoading.value = false
    }
  }

  const executeJob = async (jobId: string) => {
    try {
      executingJobs.value.add(jobId)
      await jobApi.executeJobNow(jobId)
      ElMessage.success('任务已触发执行')

      // 刷新列表和详情
      await fetchJobs()
      if (selectedJobId.value === jobId && jobDetail.value) {
        await fetchJobDetail(jobId)
      }
    } catch (error: any) {
      console.error('执行任务失败:', error)
      ElMessage.error('执行任务失败')
      throw error
    } finally {
      executingJobs.value.delete(jobId)
    }
  }

  const pauseJob = async (jobId: string) => {
    try {
      await jobApi.pauseJob(jobId)
      ElMessage.success('任务已暂停')
      await fetchJobs()
      if (selectedJobId.value === jobId && jobDetail.value) {
        await fetchJobDetail(jobId)
      }
    } catch (error: any) {
      console.error('暂停任务失败:', error)
      ElMessage.error('暂停任务失败')
      throw error
    }
  }

  const resumeJob = async (jobId: string) => {
    try {
      await jobApi.resumeJob(jobId)
      ElMessage.success('任务已恢复')
      await fetchJobs()
      if (selectedJobId.value === jobId && jobDetail.value) {
        await fetchJobDetail(jobId)
      }
    } catch (error: any) {
      console.error('恢复任务失败:', error)
      ElMessage.error('恢复任务失败')
      throw error
    }
  }

  const deleteJob = async (jobId: string) => {
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

      await jobApi.deleteJob(jobId)
      ElMessage.success('任务已删除')

      // 从选中列表中移除
      selectedJobs.value = selectedJobs.value.filter((id) => id !== jobId)

      // 刷新列表
      await fetchJobs()

      // 如果详情页显示的是这个任务，关闭详情
      if (selectedJobId.value === jobId) {
        closeDetail()
      }
    } catch (error: any) {
      if (error !== 'cancel') {
        console.error('删除任务失败:', error)
        ElMessage.error('删除任务失败')
        throw error
      }
    }
  }

  const openDetail = async (jobId: string) => {
    selectedJobId.value = jobId
    detailDrawerVisible.value = true

    // 如果还没有加载详情，则加载
    if (!jobDetail.value || jobDetail.value.job.job_id !== jobId) {
      await fetchJobDetail(jobId)
    }
  }

  const closeDetail = () => {
    detailDrawerVisible.value = false
    selectedJobId.value = undefined
    // 延迟清空详情数据，避免动画期间内容消失
    setTimeout(() => {
      if (!detailDrawerVisible.value) {
        jobDetail.value = null
      }
    }, 300)
  }

  const selectJob = (jobId: string) => {
    if (!selectedJobs.value.includes(jobId)) {
      selectedJobs.value.push(jobId)
    }
  }

  const deselectJob = (jobId: string) => {
    selectedJobs.value = selectedJobs.value.filter((id) => id !== jobId)
  }

  const toggleSelectJob = (jobId: string) => {
    if (selectedJobs.value.includes(jobId)) {
      deselectJob(jobId)
    } else {
      selectJob(jobId)
    }
  }

  const selectAll = () => {
    jobs.value.forEach((job) => {
      if (!selectedJobs.value.includes(job.job_id)) {
        selectedJobs.value.push(job.job_id)
      }
    })
  }

  const deselectAll = () => {
    selectedJobs.value = []
  }

  const clearSelection = () => {
    selectedJobs.value = []
  }

  const setSearchKeyword = (keyword: string) => {
    searchKeyword.value = keyword
    currentPage.value = 1
  }

  const setStatusFilter = (status: JobStatus | '') => {
    statusFilter.value = status
    currentPage.value = 1
  }

  const setJobTypeFilter = (type: JobType | '') => {
    jobTypeFilter.value = type
    currentPage.value = 1
  }

  const setPage = (page: number) => {
    currentPage.value = page
  }

  const setPageSize = (size: number) => {
    pageSize.value = size
    currentPage.value = 1
  }

  const refresh = async () => {
    await fetchJobs()
    if (selectedJobId.value && jobDetail.value) {
      await fetchJobDetail(selectedJobId.value)
    }
  }

  const isExecuting = (jobId: string) => {
    return executingJobs.value.has(jobId)
  }

  return {
    // State
    jobs,
    loading,
    total,
    currentPage,
    pageSize,
    searchKeyword,
    statusFilter,
    jobTypeFilter,
    selectedJobs,
    detailDrawerVisible,
    selectedJobId,
    jobDetail,
    detailLoading,
    executingJobs,

    // Computed
    isAllSelected,
    isIndeterminate,
    filteredJobs,

    // Actions
    fetchJobs,
    fetchJobDetail,
    executeJob,
    pauseJob,
    resumeJob,
    deleteJob,
    openDetail,
    closeDetail,
    selectJob,
    deselectJob,
    toggleSelectJob,
    selectAll,
    deselectAll,
    clearSelection,
    setSearchKeyword,
    setStatusFilter,
    setJobTypeFilter,
    setPage,
    setPageSize,
    refresh,
    isExecuting,
  }
})
