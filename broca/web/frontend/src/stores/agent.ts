import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

export interface AgentConfig {
  id: string
  name: string
  description: string
  status: 'active' | 'inactive' | 'error'
  type: string
  created_at: string
  updated_at: string
  config: {
    model: string
    temperature: number
    max_tokens: number
    system_prompt: string
    tools: string[]
    [key: string]: any
  }
}

export interface Agent {
  id: string
  name: string
  description: string
  status: 'idle' | 'running' | 'connecting' | 'disconnected'
  type: string
  config_id: string
  created_at: string
  session_id?: string
  metrics?: {
    total_messages: number
    avg_response_time: number
    success_rate: number
  }
}

export const useAgentStore = defineStore('agent', () => {
  const agents = ref<Agent[]>([])
  const agentConfigs = ref<AgentConfig[]>([])
  const selectedAgentId = ref<string>('')
  const loading = ref(false)
  const error = ref<string>('')

  const selectedAgent = ref<Agent | null>(null)
  const selectedAgentConfig = ref<AgentConfig | null>(null)

  const mockAgents: Agent[] = [
    {
      id: 'main_agent',
      name: 'Main Assistant',
      description: '主要助手，负责处理一般对话和任务',
      status: 'idle',
      type: 'assistant',
      config_id: 'config_001',
      created_at: '2024-01-01T00:00:00Z',
      metrics: {
        total_messages: 1250,
        avg_response_time: 1.2,
        success_rate: 95.5
      }
    },
    {
      id: 'code_agent',
      name: 'Code Assistant',
      description: '代码助手，专门处理编程相关任务',
      status: 'running',
      type: 'code_assistant',
      config_id: 'config_002',
      created_at: '2024-01-02T00:00:00Z',
      metrics: {
        total_messages: 850,
        avg_response_time: 2.1,
        success_rate: 92.3
      }
    },
    {
      id: 'research_agent',
      name: 'Research Assistant',
      description: '研究助手，负责信息检索和分析',
      status: 'idle',
      type: 'research_assistant',
      config_id: 'config_003',
      created_at: '2024-01-03T00:00:00Z',
      metrics: {
        total_messages: 420,
        avg_response_time: 3.5,
        success_rate: 88.7
      }
    },
    {
      id: 'task_agent',
      name: 'Task Manager',
      description: '任务管理助手，负责规划和跟踪任务',
      status: 'disconnected',
      type: 'task_manager',
      config_id: 'config_004',
      created_at: '2024-01-04T00:00:00Z',
      metrics: {
        total_messages: 680,
        avg_response_time: 1.8,
        success_rate: 96.2
      }
    },
    {
      id: 'data_agent',
      name: 'Data Analyst',
      description: '数据分析助手，处理数据分析和可视化',
      status: 'connecting',
      type: 'data_analyst',
      config_id: 'config_005',
      created_at: '2024-01-05T00:00:00Z',
      metrics: {
        total_messages: 320,
        avg_response_time: 4.2,
        success_rate: 85.4
      }
    }
  ]

  const mockAgentConfigs: AgentConfig[] = [
    {
      id: 'config_001',
      name: 'Main Assistant Config',
      description: '主要助手的配置',
      status: 'active',
      type: 'assistant',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-10T00:00:00Z',
      config: {
        model: 'gpt-4',
        temperature: 0.7,
        max_tokens: 2000,
        system_prompt: '你是一个有用的助手，请帮助用户解决问题。',
        tools: ['web_search', 'calculator', 'file_reader']
      }
    },
    {
      id: 'config_002',
      name: 'Code Assistant Config',
      description: '代码助手的配置',
      status: 'active',
      type: 'code_assistant',
      created_at: '2024-01-02T00:00:00Z',
      updated_at: '2024-01-11T00:00:00Z',
      config: {
        model: 'gpt-4-code',
        temperature: 0.3,
        max_tokens: 4000,
        system_prompt: '你是一个专业的编程助手，请帮助用户编写、调试和优化代码。',
        tools: ['code_executor', 'debugger', 'code_analyzer', 'git_operations']
      }
    },
    {
      id: 'config_003',
      name: 'Research Assistant Config',
      description: '研究助手的配置',
      status: 'active',
      type: 'research_assistant',
      created_at: '2024-01-03T00:00:00Z',
      updated_at: '2024-01-12T00:00:00Z',
      config: {
        model: 'gpt-4-research',
        temperature: 0.5,
        max_tokens: 3000,
        system_prompt: '你是一个研究助手，请帮助用户收集、分析和整理信息。',
        tools: ['web_search', 'document_analyzer', 'summarizer', 'citation_generator']
      }
    },
    {
      id: 'config_004',
      name: 'Task Manager Config',
      description: '任务管理助手的配置',
      status: 'active',
      type: 'task_manager',
      created_at: '2024-01-04T00:00:00Z',
      updated_at: '2024-01-13T00:00:00Z',
      config: {
        model: 'gpt-4',
        temperature: 0.4,
        max_tokens: 2500,
        system_prompt: '你是一个任务管理助手，请帮助用户规划、跟踪和管理任务。',
        tools: ['task_creator', 'progress_tracker', 'calendar_integration', 'reminder_system']
      }
    },
    {
      id: 'config_005',
      name: 'Data Analyst Config',
      description: '数据分析助手的配置',
      status: 'active',
      type: 'data_analyst',
      created_at: '2024-01-05T00:00:00Z',
      updated_at: '2024-01-14T00:00:00Z',
      config: {
        model: 'gpt-4-data',
        temperature: 0.6,
        max_tokens: 3500,
        system_prompt: '你是一个数据分析助手，请帮助用户分析数据、生成报告和可视化。',
        tools: ['data_processor', 'statistical_analyzer', 'chart_generator', 'report_builder']
      }
    }
  ]

  const fetchAgents = async () => {
    loading.value = true
    error.value = ''
    
    try {
      // TODO: 替换为实际的API调用
      // const response = await agentApi.getAgents()
      // agents.value = response.agents
      
      // 暂时使用模拟数据
      await new Promise(resolve => setTimeout(resolve, 500))
      agents.value = mockAgents
      
      if (agents.value.length > 0 && !selectedAgentId.value) {
        const firstAgent = agents.value[0]
        if (firstAgent) {
          selectedAgentId.value = firstAgent.id
          selectAgent(firstAgent.id)
        }
      }
    } catch (err: any) {
      error.value = err.message || '获取Agent列表失败'
      ElMessage.error(error.value)
    } finally {
      loading.value = false
    }
  }

  const fetchAgentConfigs = async () => {
    loading.value = true
    error.value = ''
    
    try {
      // TODO: 替换为实际的API调用
      // const response = await agentApi.getAgentConfigs()
      // agentConfigs.value = response.configs
      
      // 暂时使用模拟数据
      await new Promise(resolve => setTimeout(resolve, 500))
      agentConfigs.value = mockAgentConfigs
    } catch (err: any) {
      error.value = err.message || '获取Agent配置失败'
      ElMessage.error(error.value)
    } finally {
      loading.value = false
    }
  }

  const selectAgent = (agentId: string) => {
    selectedAgentId.value = agentId
    selectedAgent.value = agents.value.find(agent => agent.id === agentId) || null
    
    if (selectedAgent.value) {
      selectedAgentConfig.value = agentConfigs.value.find(
        config => config.id === selectedAgent.value?.config_id
      ) || null
    }
  }

  const getAgentById = (agentId: string): Agent | undefined => {
    return agents.value.find(agent => agent.id === agentId)
  }

  const getAgentConfigById = (configId: string): AgentConfig | undefined => {
    return agentConfigs.value.find(config => config.id === configId)
  }

  const updateAgentStatus = (agentId: string, status: Agent['status']) => {
    const agent = agents.value.find(a => a.id === agentId)
    if (agent) {
      agent.status = status
      if (agentId === selectedAgentId.value) {
        selectedAgent.value = { ...agent }
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

  const init = async () => {
    await Promise.all([
      fetchAgents(),
      fetchAgentConfigs()
    ])
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
    fetchAgentConfigs,
    selectAgent,
    getAgentById,
    getAgentConfigById,
    updateAgentStatus,
    getStatusColor,
    getStatusText,
    getTypeIcon,
    getTypeColor,
    init
  }
})