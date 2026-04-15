import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { taskApi, type Task, TaskStatus, TaskPriority, type TaskDetail } from '@/api/task'

export const useTaskStore = defineStore('task', () => {
  // 状态
  const tasks = ref<Task[]>([])
  const loading = ref(false)
  const total = ref(0)
  const currentPage = ref(1)
  const pageSize = ref(20)

  // 筛选条件
  const searchKeyword = ref('')
  const statusFilter = ref<TaskStatus | ''>('')
  const priorityFilter = ref<TaskPriority | ''>('')
  const assigneeFilter = ref<string>('')
  const sessionFilter = ref<string>('')
  const parentFilter = ref<string>('')

  // 选中的任务
  const selectedTasks = ref<string[]>([])

  // 详情相关
  const detailDrawerVisible = ref(false)
  const selectedTaskId = ref<string | undefined>(undefined)
  const taskDetail = ref<TaskDetail | null>(null)
  const detailLoading = ref(false)

  // 计算属性
  const isAllSelected = computed(() => {
    return tasks.value.length > 0 && selectedTasks.value.length === tasks.value.length
  })

  const isIndeterminate = computed(() => {
    return selectedTasks.value.length > 0 && selectedTasks.value.length < tasks.value.length
  })

  const filteredTasks = computed(() => {
    let result = tasks.value

    // 关键词搜索（已经在API层处理，这里可以再做一层保险）
    if (searchKeyword.value) {
      const keyword = searchKeyword.value.toLowerCase()
      result = result.filter(
        (task) =>
          task.name.toLowerCase().includes(keyword) ||
          task.task_id.toLowerCase().includes(keyword) ||
          task.description.toLowerCase().includes(keyword) ||
          (task.details && task.details.toLowerCase().includes(keyword))
      )
    }

    return result
  })

  // Actions
  const fetchTasks = async (params?: {
    skip?: number
    limit?: number
    status?: TaskStatus
    priority?: TaskPriority
    assignee?: string
    session_id?: string
    parent_id?: string
    keyword?: string
    order_by?: string
  }) => {
    loading.value = true

    try {
      const response = await taskApi.getTasks({
        skip: params?.skip ?? (currentPage.value - 1) * pageSize.value,
        limit: params?.limit ?? pageSize.value,
        status: params?.status ?? (statusFilter.value || undefined),
        priority: params?.priority ?? (priorityFilter.value || undefined),
        assignee: params?.assignee ?? (assigneeFilter.value || undefined),
        session_id: params?.session_id ?? (sessionFilter.value || undefined),
        parent_id: params?.parent_id ?? (parentFilter.value || undefined),
        keyword: params?.keyword ?? (searchKeyword.value || undefined),
        order_by: params?.order_by ?? 'created_at desc',
      })

      tasks.value = response.tasks
      total.value = response.total
      currentPage.value = params?.skip
        ? Math.floor(params.skip / (params.limit || pageSize.value)) + 1
        : currentPage.value
    } catch (error: any) {
      console.error('获取任务列表失败:', error)
      ElMessage.error('加载任务列表失败')
      throw error
    } finally {
      loading.value = false
    }
  }

  const fetchTaskDetail = async (taskId: string) => {
    detailLoading.value = true

    try {
      const response = await taskApi.getTaskDetail(taskId)
      taskDetail.value = response
      return response
    } catch (error: any) {
      console.error('获取任务详情失败:', error)
      ElMessage.error('加载任务详情失败')
      taskDetail.value = null
      throw error
    } finally {
      detailLoading.value = false
    }
  }

  const createTask = async (taskData: any) => {
    try {
      const response = await taskApi.createTask(taskData)
      ElMessage.success('任务创建成功')

      // 刷新列表
      await fetchTasks()
      return response.task
    } catch (error: any) {
      console.error('创建任务失败:', error)
      ElMessage.error('创建任务失败')
      throw error
    }
  }

  const updateTask = async (taskId: string, updateData: any) => {
    try {
      await taskApi.updateTask(taskId, updateData)
      ElMessage.success('任务更新成功')

      // 刷新列表和详情
      await fetchTasks()
      if (selectedTaskId.value === taskId && taskDetail.value) {
        await fetchTaskDetail(taskId)
      }
    } catch (error: any) {
      console.error('更新任务失败:', error)
      ElMessage.error('更新任务失败')
      throw error
    }
  }

  const deleteTask = async (taskId: string) => {
    try {
      await ElMessageBox.confirm('确定要删除这个任务吗？此操作不可恢复。', '确认删除', {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      })

      await taskApi.deleteTask(taskId)
      ElMessage.success('任务已删除')

      // 从选中列表中移除
      selectedTasks.value = selectedTasks.value.filter((id) => id !== taskId)

      // 刷新列表
      await fetchTasks()

      // 如果详情页显示的是这个任务，关闭详情
      if (selectedTaskId.value === taskId) {
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

  const addComment = async (taskId: string, author: string, content: string) => {
    try {
      const response = await taskApi.addTaskComment(taskId, { author, content })
      ElMessage.success('评论添加成功')

      // 刷新详情
      if (selectedTaskId.value === taskId && taskDetail.value) {
        await fetchTaskDetail(taskId)
      }

      return response.comment
    } catch (error: any) {
      console.error('添加评论失败:', error)
      ElMessage.error('添加评论失败')
      throw error
    }
  }

  const openDetail = async (taskId: string) => {
    selectedTaskId.value = taskId
    detailDrawerVisible.value = true

    // 如果还没有加载详情，则加载
    if (!taskDetail.value || taskDetail.value.task.task_id !== taskId) {
      await fetchTaskDetail(taskId)
    }
  }

  const closeDetail = () => {
    detailDrawerVisible.value = false
    selectedTaskId.value = undefined
    // 延迟清空详情数据，避免动画期间内容消失
    setTimeout(() => {
      if (!detailDrawerVisible.value) {
        taskDetail.value = null
      }
    }, 300)
  }

  const selectTask = (taskId: string) => {
    if (!selectedTasks.value.includes(taskId)) {
      selectedTasks.value.push(taskId)
    }
  }

  const deselectTask = (taskId: string) => {
    selectedTasks.value = selectedTasks.value.filter((id) => id !== taskId)
  }

  const toggleSelectTask = (taskId: string) => {
    if (selectedTasks.value.includes(taskId)) {
      deselectTask(taskId)
    } else {
      selectTask(taskId)
    }
  }

  const selectAll = () => {
    tasks.value.forEach((task) => {
      if (!selectedTasks.value.includes(task.task_id)) {
        selectedTasks.value.push(task.task_id)
      }
    })
  }

  const deselectAll = () => {
    selectedTasks.value = []
  }

  const clearSelection = () => {
    selectedTasks.value = []
  }

  const setSearchKeyword = (keyword: string) => {
    searchKeyword.value = keyword
    currentPage.value = 1
  }

  const setStatusFilter = (status: TaskStatus | '') => {
    statusFilter.value = status
    currentPage.value = 1
  }

  const setPriorityFilter = (priority: TaskPriority | '') => {
    priorityFilter.value = priority
    currentPage.value = 1
  }

  const setAssigneeFilter = (assignee: string) => {
    assigneeFilter.value = assignee
    currentPage.value = 1
  }

  const setSessionFilter = (sessionId: string) => {
    sessionFilter.value = sessionId
    currentPage.value = 1
  }

  const setParentFilter = (parentId: string) => {
    parentFilter.value = parentId
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
    await fetchTasks()
    if (selectedTaskId.value && taskDetail.value) {
      await fetchTaskDetail(selectedTaskId.value)
    }
  }

  const searchTasks = async (query: string, sessionId?: string) => {
    try {
      const response = await taskApi.searchTasks({ query, session_id: sessionId })
      tasks.value = response.tasks
      total.value = response.total
      return response
    } catch (error: any) {
      console.error('搜索任务失败:', error)
      ElMessage.error('搜索任务失败')
      throw error
    }
  }

  return {
    // State
    tasks,
    loading,
    total,
    currentPage,
    pageSize,
    searchKeyword,
    statusFilter,
    priorityFilter,
    assigneeFilter,
    sessionFilter,
    parentFilter,
    selectedTasks,
    detailDrawerVisible,
    selectedTaskId,
    taskDetail,
    detailLoading,

    // Computed
    isAllSelected,
    isIndeterminate,
    filteredTasks,

    // Actions
    fetchTasks,
    fetchTaskDetail,
    createTask,
    updateTask,
    deleteTask,
    addComment,
    openDetail,
    closeDetail,
    selectTask,
    deselectTask,
    toggleSelectTask,
    selectAll,
    deselectAll,
    clearSelection,
    setSearchKeyword,
    setStatusFilter,
    setPriorityFilter,
    setAssigneeFilter,
    setSessionFilter,
    setParentFilter,
    setPage,
    setPageSize,
    refresh,
    searchTasks,
  }
})
