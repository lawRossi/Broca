import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { crewApi, type CrewExecution, type ExecutionStatus, type CrewConfig, type CrewConfigFile, type CrewConfigDetail } from '@/api/crew'

let _crewEventHandlerRegistered = false

export const useCrewStore = defineStore('crew', () => {
  // 状态
  const executions = ref<CrewExecution[]>([])
  const loading = ref(false)
  const total = ref(0)

  // 筛选条件
  const sessionFilter = ref<string>('')
  const statusFilter = ref<string>('')

  // 详情相关
  const detailDrawerVisible = ref(false)
  const selectedExecutionId = ref<string | undefined>(undefined)
  const executionDetail = ref<CrewExecution | null>(null)
  const detailLoading = ref(false)

  // 提交相关
  const submitting = ref(false)
  const yamlEditorVisible = ref(false)
  const yamlContent = ref('')
  const validationErrors = ref<string[]>([])

  // Workspace crew_configs 相关
  const configFiles = ref<CrewConfigFile[]>([])
  const configFilesLoading = ref(false)
  const selectedConfigFile = ref<CrewConfigDetail | null>(null)
  const configDetailLoading = ref(false)
  const activeWorkspace = ref<string>('')

  // 当前编辑中的文件路径（用于保存回写）
  const currentEditedFilePath = ref<string>('')
  const currentEditedFilename = ref<string>('')
  const saving = ref(false)

  // Actions
  const fetchExecutions = async (params?: {
    session_id?: string
    status?: string
  }) => {
    loading.value = true
    try {
      const response = await crewApi.list({
        session_id: params?.session_id ?? (sessionFilter.value || undefined),
        status: params?.status ?? (statusFilter.value || undefined),
      })
      executions.value = response.executions
      total.value = response.total
    } catch (error: any) {
      console.error('获取编排列表失败:', error)
      ElMessage.error('加载编排列表失败')
      throw error
    } finally {
      loading.value = false
    }
  }

  const fetchDetail = async (executionId: string) => {
    detailLoading.value = true
    try {
      const response = await crewApi.getDetail(executionId)
      executionDetail.value = response
      return response
    } catch (error: any) {
      console.error('获取编排详情失败:', error)
      ElMessage.error('加载编排详情失败')
      executionDetail.value = null
      throw error
    } finally {
      detailLoading.value = false
    }
  }

  const submitCrew = async (yaml: string, sessionId: string) => {
    submitting.value = true
    try {
      const result = await crewApi.submit({
        yaml_content: yaml,
        session_id: sessionId,
      })
      ElMessage.success('编排已提交')
      yamlEditorVisible.value = false
      yamlContent.value = ''
      validationErrors.value = []
      await fetchExecutions()
      return result
    } catch (error: any) {
      console.error('提交编排失败:', error)
      ElMessage.error(error.message || '提交编排失败')
      throw error
    } finally {
      submitting.value = false
    }
  }

  const submitCrewByPath = async (yamlPath: string, sessionId: string) => {
    submitting.value = true
    try {
      const result = await crewApi.submit({
        yaml_path: yamlPath,
        session_id: sessionId,
      })
      ElMessage.success('编排已提交')
      await fetchExecutions()
      return result
    } catch (error: any) {
      console.error('提交编排失败:', error)
      ElMessage.error(error.message || '提交编排失败')
      throw error
    } finally {
      submitting.value = false
    }
  }

  const validateYaml = async (yaml: string): Promise<boolean> => {
    try {
      const result = await crewApi.validate({ yaml_content: yaml })
      validationErrors.value = result.errors
      if (result.valid) {
        ElMessage.success('配置校验通过')
      } else {
        ElMessage.warning(`配置有 ${result.error_count} 个错误`)
      }
      return result.valid
    } catch (error: any) {
      console.error('校验失败:', error)
      validationErrors.value = [error.message || '校验请求失败']
      return false
    }
  }

  const abortExecution = async (executionId: string) => {
    try {
      await ElMessageBox.confirm('确定要中止此编排执行吗？', '确认中止', {
        confirmButtonText: '确定中止',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await crewApi.abort(executionId)
      ElMessage.success('编排已中止')
      await fetchExecutions()
      if (selectedExecutionId.value === executionId) {
        await fetchDetail(executionId)
      }
    } catch (error: any) {
      if (error !== 'cancel') {
        console.error('中止编排失败:', error)
        ElMessage.error('中止编排失败')
      }
    }
  }

  const deleteExecution = async (executionId: string) => {
    try {
      await ElMessageBox.confirm('确定要删除此编排执行记录吗？', '确认删除', {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await crewApi.delete(executionId)
      ElMessage.success('编排已删除')
      executions.value = executions.value.filter(e => e.execution_id !== executionId)
      if (selectedExecutionId.value === executionId) {
        closeDetail()
      }
    } catch (error: any) {
      if (error !== 'cancel') {
        console.error('删除编排失败:', error)
        ElMessage.error('删除编排失败')
      }
    }
  }

  const openDetail = async (executionId: string) => {
    selectedExecutionId.value = executionId
    detailDrawerVisible.value = true
    if (!executionDetail.value || executionDetail.value.execution_id !== executionId) {
      await fetchDetail(executionId)
    }
  }

  const closeDetail = () => {
    detailDrawerVisible.value = false
    selectedExecutionId.value = undefined
    setTimeout(() => {
      if (!detailDrawerVisible.value) {
        executionDetail.value = null
      }
    }, 300)
  }

  // ==========================================================================
  // Workspace crew_configs 相关 Actions
  // ==========================================================================

  const setActiveWorkspace = (workspace: string) => {
    activeWorkspace.value = workspace
  }

  const fetchConfigFiles = async (workspace?: string) => {
    const ws = workspace || activeWorkspace.value
    if (!ws) {
      configFiles.value = []
      return
    }
    configFilesLoading.value = true
    try {
      const response = await crewApi.listConfigs(ws)
      configFiles.value = response.configs
      activeWorkspace.value = ws
    } catch (error: any) {
      console.error('获取编排配置文件列表失败:', error)
      configFiles.value = []
      // 不弹错误提示，因为 workspace 可能还没有 crew_configs 目录
    } finally {
      configFilesLoading.value = false
    }
  }

  const fetchConfigDetail = async (filename: string, workspace?: string) => {
    const ws = workspace || activeWorkspace.value
    if (!ws) return null
    configDetailLoading.value = true
    try {
      const detail = await crewApi.getConfigDetail(filename, ws)
      selectedConfigFile.value = detail
      return detail
    } catch (error: any) {
      console.error('获取编排配置文件详情失败:', error)
      ElMessage.error('加载编排配置失败')
      selectedConfigFile.value = null
      return null
    } finally {
      configDetailLoading.value = false
    }
  }

  const loadConfigIntoEditor = async (filename: string, workspace?: string) => {
    const detail = await fetchConfigDetail(filename, workspace)
    if (detail) {
      yamlContent.value = detail.content
      currentEditedFilePath.value = detail.path
      currentEditedFilename.value = detail.filename
      validationErrors.value = []
      yamlEditorVisible.value = true
    }
  }

  const saveConfigFile = async (content: string): Promise<boolean> => {
    if (!activeWorkspace.value || !currentEditedFilename.value) {
      ElMessage.warning('没有可保存的目标文件')
      return false
    }
    saving.value = true
    try {
      await crewApi.saveConfig(currentEditedFilename.value, activeWorkspace.value, content)
      ElMessage.success('配置已保存')
      yamlContent.value = content
      // 刷新配置文件列表
      await fetchConfigFiles(activeWorkspace.value)
      return true
    } catch (error: any) {
      console.error('保存配置失败:', error)
      ElMessage.error(error.message || '保存配置失败')
      return false
    } finally {
      saving.value = false
    }
  }

  const openYamlEditor = (prefilledYaml?: string) => {
    yamlEditorVisible.value = true
    validationErrors.value = []
    currentEditedFilePath.value = ''
    currentEditedFilename.value = ''
    if (prefilledYaml) {
      yamlContent.value = prefilledYaml
    }
  }

  const closeYamlEditor = () => {
    yamlEditorVisible.value = false
    yamlContent.value = ''
    validationErrors.value = []
    currentEditedFilePath.value = ''
    currentEditedFilename.value = ''
  }

  const setSessionFilter = (sessionId: string) => {
    sessionFilter.value = sessionId
  }

  const setStatusFilter = (status: string) => {
    statusFilter.value = status
  }

  const refresh = async () => {
    await fetchExecutions()
    if (selectedExecutionId.value && executionDetail.value) {
      await fetchDetail(selectedExecutionId.value)
    }
  }

  // ==========================================================================
  // Socket.IO 实时更新
  // ==========================================================================

  const initSocketSubscription = () => {
    if (_crewEventHandlerRegistered) return
    _crewEventHandlerRegistered = true

    // 延迟导入避免循环依赖
    import('@/stores/socket').then(({ useSocketStore }) => {
      const socketStore = useSocketStore()
      socketStore.onCrewEvent = (event: string, data: any) => {
        // 更新列表中的记录
        if (data?.execution_id) {
          const idx = executions.value.findIndex(e => e.execution_id === data.execution_id)
          if (idx >= 0) {
            executions.value[idx] = data as CrewExecution
            // 触发响应式更新
            executions.value = [...executions.value]
          }
          // 如果正在查看该执行记录的详情，同步更新
          if (selectedExecutionId.value === data.execution_id && executionDetail.value) {
            executionDetail.value = data as CrewExecution
          }
        }
      }
    })
  }

  // 初始化时注册
  initSocketSubscription()

  return {
    // State
    executions,
    loading,
    total,
    sessionFilter,
    statusFilter,
    detailDrawerVisible,
    selectedExecutionId,
    executionDetail,
    detailLoading,
    submitting,
    yamlEditorVisible,
    yamlContent,
    validationErrors,

    // Workspace crew_configs state
    configFiles,
    configFilesLoading,
    selectedConfigFile,
    configDetailLoading,
    activeWorkspace,
    currentEditedFilePath,
    currentEditedFilename,
    saving,

    // Actions
    fetchExecutions,
    fetchDetail,
    submitCrew,
    submitCrewByPath,
    validateYaml,
    abortExecution,
    deleteExecution,
    openDetail,
    closeDetail,
    openYamlEditor,
    closeYamlEditor,
    setSessionFilter,
    setStatusFilter,
    refresh,

    // Workspace crew_configs actions
    setActiveWorkspace,
    fetchConfigFiles,
    fetchConfigDetail,
    loadConfigIntoEditor,
    saveConfigFile,
  }
})
