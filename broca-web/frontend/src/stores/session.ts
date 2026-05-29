import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { sessionApi, type Session, type CreateSessionParams, type UpdateSessionParams } from '@/api/session'
import { filesApi, type FileItem } from '@/api/files'

export const useSessionStore = defineStore('session', () => {
  // State
  const sessions = ref<Session[]>([])
  const loading = ref(false)
  const total = ref(0)
  const currentPage = ref(1)
  const pageSize = ref(20)
  const searchKeyword = ref('')
  const selectedSessions = ref<string[]>([])

  // Dialog states
  const createDialogVisible = ref(false)
  const creating = ref(false)
  const deleteLoading = ref(false)

  // Form state
  const createForm = ref<CreateSessionParams>({
    description: '',
    workspace: '',
    provider: undefined,
    model: undefined,
    category: 'normal',
  })

  // Workspace suggestions
  const workspaceAllSuggestions = ref<string[]>([])

  // Workspace picker
  const workspacePickerVisible = ref(false)

  // Home directory
  const homeDirectory = ref<string>('')

  const isAllSelected = computed(() => {
    return sessions.value.length > 0 && selectedSessions.value.length === sessions.value.length
  })

  const isIndeterminate = computed(() => {
    return selectedSessions.value.length > 0 && selectedSessions.value.length < sessions.value.length
  })

  // Actions
  const fetchSessions = async (params?: { skip?: number; limit?: number; keyword?: string }) => {
    loading.value = true

    try {
      const response = await sessionApi.getSessions({
        skip: params?.skip ?? (currentPage.value - 1) * pageSize.value,
        limit: params?.limit ?? pageSize.value,
        keyword: params?.keyword ?? (searchKeyword.value || undefined),
      })

      sessions.value = response.sessions || []
      total.value = response.total || 0
    } catch (error: any) {
      console.error('获取会话列表失败:', error)
      ElMessage.error('加载会话列表失败')
      throw error
    } finally {
      loading.value = false
    }
  }

  const createSession = async (params: CreateSessionParams, autoCloseDialog = true) => {
    creating.value = true

    try {
      // silent=true: 关闭 Axios 拦截器的 ElMessage 弹窗，由本 catch 块统一处理错误展示
      const response = await sessionApi.createSession({
        description: params.description || undefined,
        workspace: params.workspace || undefined,
        provider: params.provider || undefined,
        model: params.model || undefined,
        category: params.category || 'normal',
      }, true)

      ElMessage.success('会话创建成功')

      // 将新创建的会话立即插入到列表最前面
      if (response?.session_id) {
        const newSession: Session = {
          session_id: response.session_id,
          description: response.description || params.description,
          workspace: response.workspace || params.workspace || '',
          category: params.category || 'normal',
          created_at: new Date().toISOString(),
          runner_status: 'starting',
        }
        sessions.value.unshift(newSession)
        total.value += 1
      }

      // 重置表单（不自动关闭对话框，由调用方决定何时关闭）
      resetCreateForm()
      if (autoCloseDialog) {
        createDialogVisible.value = false
      }

      // 后台刷新列表以确保数据一致性
      setTimeout(() => fetchSessions(), 300)

      return response
    } catch (error: any) {
      console.error('创建会话失败:', error)
      // 从后端响应中提取真实错误消息（优先用服务器返回的 msg/detail）
      const responseMsg = error?.response?.data?.msg || error?.response?.data?.detail || ''
      const msg = responseMsg || error.message || '未知错误'
      // Agent 编排会话无自定义 Agent 时给出明确指引
      if (params.category === 'agent-orchestration' && msg.includes('自定义 Agent')) {
        ElMessage.warning({
          message: '未找到自定义 Agent 配置，已在创建页面切换为普通会话',
          duration: 5000,
        })
      } else if (responseMsg) {
        // 已有后端真实错误消息，直接展示（不加前缀避免冗余）
        ElMessage.error(msg)
      } else {
        ElMessage.error('创建会话失败: ' + msg)
      }
      throw error
    } finally {
      creating.value = false
    }
  }

  const deletingSessions = ref<Set<string>>(new Set())

  const isDeleting = (sessionId: string) => deletingSessions.value.has(sessionId)

  const deleteSession = async (sessionId: string) => {
    if (deletingSessions.value.has(sessionId)) return

    deletingSessions.value = new Set(deletingSessions.value).add(sessionId)
    try {
      await sessionApi.deleteSession(sessionId)
      ElMessage.success('会话已删除')

      // 从选中列表中移除
      selectedSessions.value = selectedSessions.value.filter((id) => id !== sessionId)

      // 从本地列表中移除
      sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
      total.value = Math.max(0, total.value - 1)

      // 如果当前页没有数据了且不是第一页，跳转到前一页
      if (sessions.value.length === 0 && currentPage.value > 1) {
        currentPage.value = 1
        await fetchSessions()
      } else {
        // 延迟刷新列表以确保数据一致性
        setTimeout(fetchSessions, 500)
      }
    } catch (error: any) {
      console.error('删除会话失败:', error)
      ElMessage.error('删除会话失败')
      throw error
    } finally {
      const newSet = new Set(deletingSessions.value)
      newSet.delete(sessionId)
      deletingSessions.value = newSet
    }
  }

  const deleteSessions = async (sessionIds: string[]) => {
    if (sessionIds.length === 0) return

    try {
      await ElMessageBox.confirm(`确定要删除选中的 ${sessionIds.length} 个会话吗？此操作不可恢复。`, '确认批量删除', {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      })

      // 标记所有待删除的会话为删除中状态
      const newSet = new Set(deletingSessions.value)
      sessionIds.forEach((id) => newSet.add(id))
      deletingSessions.value = newSet

      await sessionApi.deleteSessions(sessionIds)
      ElMessage.success(`成功删除 ${sessionIds.length} 个会话`)

      // 从选中列表中移除
      selectedSessions.value = selectedSessions.value.filter((id) => !sessionIds.includes(id))

      // 从本地列表中移除
      const deletedIds = new Set(sessionIds)
      sessions.value = sessions.value.filter((s) => !deletedIds.has(s.session_id))
      const removedCount = sessionIds.length
      total.value = Math.max(0, total.value - removedCount)

      // 如果当前页没有数据了且不是第一页，跳转到前一页
      if (sessions.value.length === 0 && currentPage.value > 1) {
        currentPage.value = 1
        await fetchSessions()
      } else {
        // 延迟刷新列表
        setTimeout(fetchSessions, 500)
      }
    } catch (error: any) {
      if (error !== 'cancel') {
        console.error('批量删除会话失败:', error)
        ElMessage.error('批量删除失败')
        throw error
      }
    } finally {
      // 清除所有标记
      const newSet = new Set(deletingSessions.value)
      sessionIds.forEach((id) => newSet.delete(id))
      deletingSessions.value = newSet
    }
  }

  const updateSession = async (sessionId: string, params: UpdateSessionParams) => {
    // if (!isLoggedIn.value) {
    //   throw new Error('用户未登录')
    // }

    try {
      await sessionApi.updateSession(sessionId, params)
      ElMessage.success('会话描述已更新')

      // 更新本地列表中的会话描述
      const sessionIndex = sessions.value.findIndex((s) => s.session_id === sessionId)
      if (sessionIndex !== -1) {
        if (params.description !== undefined) {
          sessions.value[sessionIndex].description = params.description
        }
      }

      return true
    } catch (error: any) {
      console.error('更新会话失败:', error)
      ElMessage.error('更新会话失败: ' + (error.message || '未知错误'))
      throw error
    }
  }

  // Selectors
  const selectSession = (sessionId: string) => {
    if (!selectedSessions.value.includes(sessionId)) {
      selectedSessions.value.push(sessionId)
    }
  }

  const deselectSession = (sessionId: string) => {
    selectedSessions.value = selectedSessions.value.filter((id) => id !== sessionId)
  }

  const toggleSelectSession = (sessionId: string) => {
    if (selectedSessions.value.includes(sessionId)) {
      deselectSession(sessionId)
    } else {
      selectSession(sessionId)
    }
  }

  const selectAll = () => {
    sessions.value.forEach((session) => {
      if (!selectedSessions.value.includes(session.session_id)) {
        selectedSessions.value.push(session.session_id)
      }
    })
  }

  const deselectAll = () => {
    selectedSessions.value = []
  }

  const clearSelection = () => {
    selectedSessions.value = []
  }

  // Setters
  const setSearchKeyword = (keyword: string) => {
    searchKeyword.value = keyword
    currentPage.value = 1
  }

  const setCurrentPage = (page: number) => {
    currentPage.value = page
  }

  const setPageSize = (size: number) => {
    pageSize.value = size
    currentPage.value = 1
  }

  const setCreateDialogVisible = (visible: boolean) => {
    createDialogVisible.value = visible
  }

  const setCreating = (value: boolean) => {
    creating.value = value
  }

  const setDeleteLoading = (value: boolean) => {
    deleteLoading.value = value
  }

  const setCreateForm = (form: CreateSessionParams) => {
    createForm.value = form
  }

  const setWorkspaceAllSuggestions = (suggestions: string[]) => {
    workspaceAllSuggestions.value = suggestions
  }

  const setWorkspacePickerVisible = (visible: boolean) => {
    workspacePickerVisible.value = visible
  }

  // Home directory related
  const fetchHomeDirectory = async () => {
    try {
      const response = await filesApi.getHomeDirectory()
      homeDirectory.value = response.home_dir
      return homeDirectory.value
    } catch (error: any) {
      console.error('获取home目录失败:', error)
      // 如果获取失败，使用默认值
      homeDirectory.value = '/home/ubuntu'
      return homeDirectory.value
    }
  }

  const getHomeDirectory = () => {
    return homeDirectory.value
  }

  const setHomeDirectory = (path: string) => {
    homeDirectory.value = path
  }

  // Workspace related
  const extractWorkspaceSuggestions = () => {
    const workspaces = new Set<string>()

    sessions.value.forEach((session) => {
      if (session.workspace && session.workspace.trim()) {
        workspaces.add(session.workspace.trim())
      }
    })

    try {
      const localWorkspaces = localStorage.getItem('recent_workspaces')
      if (localWorkspaces) {
        const parsed = JSON.parse(localWorkspaces)
        if (Array.isArray(parsed)) {
          parsed.forEach((ws: string) => {
            if (ws && ws.trim()) {
              workspaces.add(ws.trim())
            }
          })
        }
      }
    } catch (e) {
      console.warn('Failed to parse local workspaces:', e)
    }

    workspaceAllSuggestions.value = Array.from(workspaces).filter((ws) => ws.length > 0)
  }

  const saveRecentWorkspace = (workspace: string) => {
    try {
      const key = 'recent_workspaces'
      let recent: string[] = []
      const existing = localStorage.getItem(key)
      if (existing) {
        recent = JSON.parse(existing)
      }

      recent = recent.filter((ws) => ws !== workspace)
      recent.unshift(workspace)

      if (recent.length > 10) {
        recent = recent.slice(0, 10)
      }

      localStorage.setItem(key, JSON.stringify(recent))

      // 更新建议列表
      extractWorkspaceSuggestions()
    } catch (e) {
      console.warn('Failed to save recent workspace:', e)
    }
  }

  const selectWorkspaceFromPicker = (file: FileItem) => {
    if (file.is_dir) {
      createForm.value.workspace = file.path
      workspacePickerVisible.value = false
      saveRecentWorkspace(file.path)
    } else {
      ElMessage.warning('请选择目录而不是文件')
    }
  }

  const handleWorkspaceConfirm = (path: string) => {
    createForm.value.workspace = path
    saveRecentWorkspace(path)
  }

  const resetCreateForm = () => {
    createForm.value = {
      description: '',
      workspace: '',
      provider: undefined,
      model: undefined,
      category: 'normal',
    }
  }

  const refresh = async () => {
    await fetchSessions()
  }

  return {
    // State
    sessions,
    loading,
    total,
    currentPage,
    pageSize,
    searchKeyword,
    selectedSessions,
    createDialogVisible,
    creating,
    deleteLoading,
    deletingSessions,
    createForm,
    workspaceAllSuggestions,
    workspacePickerVisible,
    homeDirectory,

    // Computed
    //isLoggedIn,
    isAllSelected,
    isIndeterminate,

    // Actions
    fetchSessions,
    createSession,
    isDeleting,
    deleteSession,
    deleteSessions,
    updateSession,
    selectSession,
    deselectSession,
    toggleSelectSession,
    selectAll,
    deselectAll,
    clearSelection,
    setSearchKeyword,
    setCurrentPage,
    setPageSize,
    setCreateDialogVisible,
    setCreating,
    setDeleteLoading,
    setCreateForm,
    setWorkspaceAllSuggestions,
    setWorkspacePickerVisible,
    extractWorkspaceSuggestions,
    saveRecentWorkspace,
    selectWorkspaceFromPicker,
    handleWorkspaceConfirm,
    resetCreateForm,
    fetchHomeDirectory,
    getHomeDirectory,
    setHomeDirectory,
    refresh,
  }
})
