import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { agentApi, type AgentConfig as ApiAgentConfig } from '@/api/agent'
import { sessionApi, type Agent as SessionAgent } from '@/api/session'

// 使用API中的AgentConfig类型
export type AgentConfig = ApiAgentConfig

export interface Agent extends SessionAgent {
  status: 'idle' | 'running' | 'connecting' | 'disconnected'
  type: string
  metrics?: {
    total_messages: number
    avg_response_time: number
    success_rate: number
  }
}

export const useAgentStore = defineStore('agent', () => {
  const agents = ref<Agent[]>([])
  const agentConfigs = ref<Map<string, AgentConfig>>(new Map()) // 使用Map缓存配置
  const selectedAgentId = ref<string>('')
  const loading = ref(false)
  const error = ref<string>('')

  const selectedAgent = ref<Agent | null>(null)
  const selectedAgentConfig = ref<AgentConfig | null>(null)

  const fetchAgents = async (sessionId?: string) => {
    loading.value = true
    error.value = ''
    
    try {
      if (!sessionId) {
        // 如果没有提供sessionId，清空agents
        agents.value = []
        return
      }
      
      // 使用sessionApi获取session中的agents
      const sessionAgents = await sessionApi.getSessionAgents(sessionId)
      
      // 转换为Agent类型，添加默认状态
      agents.value = sessionAgents.map(agent => ({
        ...agent,
        status: 'idle' as const,
        type: agent.type || 'assistant'
      }))
      
      if (agents.value.length > 0 && !selectedAgentId.value) {
        const firstAgent = agents.value[0]
        if (firstAgent) {
          selectedAgentId.value = firstAgent.agent_id
          selectAgent(firstAgent.agent_id)
        }
      }
    } catch (err: any) {
      error.value = err.message || '获取Agent列表失败'
      ElMessage.error(error.value)
    } finally {
      loading.value = false
    }
  }

  const fetchAgentConfig = async (sessionId: string, agentId: string): Promise<AgentConfig | null> => {
    try {
      // 先从缓存中查找
      const cachedConfig = agentConfigs.value.get(`${sessionId}_${agentId}`)
      if (cachedConfig) {
        return cachedConfig
      }
      
      // 调用API获取配置
      const config = await agentApi.getAgentConfig({ sessionId, agentId })
      
      // 缓存配置
      agentConfigs.value.set(`${sessionId}_${agentId}`, config)
      
      return config
    } catch (err: any) {
      console.error('获取Agent配置失败:', err)
      // 不显示错误消息，避免干扰用户
      return null
    }
  }

  const fetchAgentConfigs = async () => {
    loading.value = true
    error.value = ''
    
    try {
      // 获取所有agent配置
      const configs = await agentApi.getAgentConfigs()
      
      // 清空缓存
      agentConfigs.value.clear()
      
      // 将配置添加到缓存（这里假设配置有sessionId和agentId信息）
      configs.forEach(config => {
        // 注意：这里需要根据实际API返回的数据结构调整
        // 假设config中有session_id和agent_id字段
        const key = `${(config as any).session_id}_${(config as any).agent_id}`
        if (key) {
          agentConfigs.value.set(key, config)
        }
      })
    } catch (err: any) {
      error.value = err.message || '获取Agent配置失败'
      ElMessage.error(error.value)
    } finally {
      loading.value = false
    }
  }

  const selectAgent = (agentId: string, sessionId?: string) => {
    selectedAgentId.value = agentId
    selectedAgent.value = agents.value.find(agent => agent.agent_id === agentId) || null
    
    // 如果提供了sessionId，尝试获取agent配置
    if (selectedAgent.value && sessionId) {
      fetchAgentConfig(sessionId, agentId).then(config => {
        selectedAgentConfig.value = config
      })
    } else {
      selectedAgentConfig.value = null
    }
  }

  const getAgentById = (agentId: string): Agent | undefined => {
    return agents.value.find(agent => agent.agent_id === agentId)
  }

  const getAgentConfigById = (sessionId: string, agentId: string): AgentConfig | undefined => {
    return agentConfigs.value.get(`${sessionId}_${agentId}`)
  }

  const updateAgentStatus = (agentId: string, status: Agent['status'], sessionId?: string) => {
    const agent = agents.value.find(a => a.agent_id === agentId)
    if (agent) {
      agent.status = status
      if (agentId === selectedAgentId.value) {
        selectedAgent.value = { ...agent }
      }
      
      // 如果有sessionId，调用API更新状态
      if (sessionId) {
        agentApi.updateAgentStatus({ sessionId, agentId, status }).catch(err => {
          console.error('更新Agent状态失败:', err)
        })
      }
    }
  }

  const getStatusColor = (status: Agent['status']): string => {
    switch (status) {
      case 'idle':
        return 'success'
      case 'running':
        return 'primary'
      case 'connecting':
        return 'warning'
      case 'disconnected':
        return 'danger'
      default:
        return 'info'
    }
  }

  const getStatusText = (status: Agent['status']): string => {
    switch (status) {
      case 'idle':
        return '空闲'
      case 'running':
        return '运行中'
      case 'connecting':
        return '连接中'
      case 'disconnected':
        return '断开连接'
      default:
        return '未知'
    }
  }

  const getTypeIcon = (type: string): string => {
    switch (type) {
      case 'assistant':
        return 'User'
      case 'code_assistant':
        return 'Document'
      case 'research_assistant':
        return 'Search'
      case 'task_manager':
        return 'List'
      case 'data_analyst':
        return 'PieChart'
      default:
        return 'QuestionFilled'
    }
  }

  const getTypeColor = (type: string): string => {
    const typeColors: Record<string, string> = {
      'assistant': 'blue',
      'code_assistant': 'green',
      'research_assistant': 'orange',
      'task_manager': 'purple',
      'data_analyst': 'cyan'
    }
    return typeColors[type] || 'gray'
  }

  const init = async (sessionId?: string) => {
    if (sessionId) {
      await fetchAgents(sessionId)
    }
    // 不自动获取所有配置，按需获取
  }

  // 清除缓存
  const clearCache = () => {
    agentConfigs.value.clear()
    agents.value = []
    selectedAgentId.value = ''
    selectedAgent.value = null
    selectedAgentConfig.value = null
  }

  return {
    agents,
    agentConfigs,
    selectedAgentId,
    selectedAgent,
    selectedAgentConfig,
    loading,
    error,
    
    fetchAgents,
    fetchAgentConfig,
    fetchAgentConfigs,
    selectAgent,
    getAgentById,
    getAgentConfigById,
    updateAgentStatus,
    getStatusColor,
    getStatusText,
    getTypeIcon,
    getTypeColor,
    init,
    clearCache
  }
})