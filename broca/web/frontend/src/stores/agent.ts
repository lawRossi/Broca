import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { agentApi, type AgentConfig as ApiAgentConfig } from '@/api/agent'
import { sessionApi, type Agent as SessionAgent } from '@/api/session'

// 使用API中的AgentConfig类型
export type AgentConfig = ApiAgentConfig

export type AgentStatus = 'idle' | 'running' | 'connecting' | 'disconnected'

export interface Agent extends SessionAgent {
  status: AgentStatus
  type: string
  // LLM 使用统计
  total_input_tokens?: number
  total_output_tokens?: number
  total_llm_calls?: number
  // 上下文信息
  last_context_length?: number
}

export const useAgentStore = defineStore('agent', () => {
  // 当前 session 的 sessionId（需要外部传入或从 chatStore 获取）
  const sessionId = ref<string>('')

  const agents = ref<Agent[]>([])
  const agentConfigs = ref<Map<string, AgentConfig>>(new Map()) // 使用Map缓存配置
  const selectedAgentId = ref<string>('')
  const loading = ref(false)
  const error = ref<string>('')

  const selectedAgent = ref<Agent | null>(null)
  const selectedAgentConfig = ref<AgentConfig | null>(null)

  // 当前选中的 agent 信息（从 chat.ts 移过来的）
  const currentAgentId = ref('main_agent')
  const currentAgentName = ref('Assistant')

  const setSessionId = (id: string) => {
    sessionId.value = id
  }

  const fetchAgents = async (sessionId?: string, isConnected?: boolean) => {
    loading.value = true
    error.value = ''
    console.log(isConnected)
  
    try {
      if (!sessionId) {
        // 如果没有提供sessionId，清空agents
        agents.value = []
        return
      }

      const originalStatusMap = new Map(agents.value.map((agent) => [agent.agent_id, agent.status]))
      const sessionAgents = await sessionApi.getSessionAgents(sessionId)

      agents.value = sessionAgents.map((agent) => ({
        ...agent,
        status: originalStatusMap.get(agent.agent_id) || (isConnected ? 'idle' : 'disconnected'),
        type: agent.type || 'assistant',
      }))

      const mainAgent = agents.value.find((agent) => agent.role === 'main_agent' || agent.role === 'main-agent')
      if (mainAgent) {
        currentAgentId.value = mainAgent.agent_id
        currentAgentName.value = mainAgent.name || 'Main Agent'
      } else if (agents.value.length > 0) {
        const firstAgent = agents.value[0]
        if (firstAgent) {
          currentAgentId.value = firstAgent.agent_id
          currentAgentName.value = firstAgent.name || 'Assistant'
        } else {
          currentAgentId.value = 'main_agent'
          currentAgentName.value = 'Assistant'
        }
      } else {
        currentAgentId.value = 'main_agent'
        currentAgentName.value = 'Assistant'
      }

      // 如果需要设置 selectedAgent（侧边栏场景）且尚未选择
      if (!selectedAgentId.value && agents.value.length > 0) {
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

  // 从 chat.ts 移过来的：更新特定agent的状态
  const updateAgentStatus = (agentId: string, status: AgentStatus) => {
    const agentIndex = agents.value.findIndex((a) => a.agent_id === agentId)
    if (agentIndex !== -1) {
      const agent = agents.value[agentIndex]
      if (agent) {
        const updatedAgent = { ...agent, status }
        agents.value.splice(agentIndex, 1, updatedAgent)
      }
    }
  }

  // 从 chat.ts 移过来的：解析输入中的@mention，返回目标agentId
  const parseMention = (text: string): { targetAgentId: string | null; cleanText: string } => {
    if (!agents.value || agents.value.length === 0) {
      return { targetAgentId: null, cleanText: text }
    }

    const mentionRegex = /@([\w\u4e00-\u9fa5\-]+)(?:\s|$)/
    const match = text.match(mentionRegex)

    if (match && match[1]) {
      const mentionName = match[1]
      const cleanText = text.replace(mentionRegex, '').trim()

      const targetAgent = agents.value.find((agent) => {
        if (!agent) return false

        const agentNameLower = agent.name?.toLowerCase() || ''
        const mentionNameLower = mentionName.toLowerCase()

        if (agentNameLower && agentNameLower === mentionNameLower) {
          return true
        }
        return false
      })

      if (targetAgent) {
        return { targetAgentId: targetAgent.agent_id, cleanText }
      } else {
        console.log('未找到匹配的agent')
      }
    }

    if (text.trim() === '@') {
      return { targetAgentId: null, cleanText: '' }
    }

    return { targetAgentId: null, cleanText: text.trim() }
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
      configs.forEach((config) => {
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
    selectedAgent.value = agents.value.find((agent) => agent.agent_id === agentId) || null

    // 如果提供了sessionId，尝试获取agent配置
    if (selectedAgent.value && sessionId) {
      fetchAgentConfig(sessionId, agentId).then((config) => {
        selectedAgentConfig.value = config
      })
    } else {
      selectedAgentConfig.value = null
    }
  }

  const getAgentById = (agentId: string): Agent | undefined => {
    return agents.value.find((agent) => agent.agent_id === agentId)
  }

  const getAgentConfigById = (sessionId: string, agentId: string): AgentConfig | undefined => {
    return agentConfigs.value.get(`${sessionId}_${agentId}`)
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
      assistant: 'blue',
      code_assistant: 'green',
      research_assistant: 'orange',
      task_manager: 'purple',
      data_analyst: 'cyan',
    }
    return typeColors[type] || 'gray'
  }

  // const init = async (sessionId?: string) => {
  //   if (sessionId) {
  //     await fetchAgents(sessionId)
  //   }
  //   // 不自动获取所有配置，按需获取
  // }

  // 清除缓存
  const clearCache = () => {
    agentConfigs.value.clear()
    agents.value = []
    selectedAgentId.value = ''
    selectedAgent.value = null
    selectedAgentConfig.value = null
  }

  return {
    // Session ID
    sessionId,
    setSessionId,

    // Agents 列表
    agents,
    agentConfigs,
    selectedAgentId,
    selectedAgent,
    selectedAgentConfig,
    loading,
    error,

    currentAgentId,
    currentAgentName,

    fetchAgents,
    fetchAgentConfig,
    fetchAgentConfigs,
    selectAgent,
    getAgentById,
    getAgentConfigById,
    updateAgentStatus,
    parseMention,
    getStatusColor,
    getStatusText,
    getTypeIcon,
    getTypeColor,
    clearCache,
  }
})
