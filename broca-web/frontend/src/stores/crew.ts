import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { crewApi, type CrewExecution, type ExecutionStatus, type CrewConfig } from '@/api/crew'

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

  const openYamlEditor = () => {
    yamlEditorVisible.value = true
    validationErrors.value = []
  }

  const closeYamlEditor = () => {
    yamlEditorVisible.value = false
    yamlContent.value = ''
    validationErrors.value = []
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

    // Actions
    fetchExecutions,
    fetchDetail,
    submitCrew,
    validateYaml,
    abortExecution,
    openDetail,
    closeDetail,
    openYamlEditor,
    closeYamlEditor,
    setSessionFilter,
    setStatusFilter,
    refresh,
  }
})
