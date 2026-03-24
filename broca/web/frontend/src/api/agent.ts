import request from '@/utils/request'
import type { Agent as SessionAgent } from './session'

export interface AgentConfig {
  config_id: string
  agent_name: string
  agent_role: string
  config_content: {
    name: string
    role: string
    llm_config_name?: string
    tools?: string[]
    workspace?: string
    [key: string]: any
  }
  created_at: string
  updated_at: string
}

export interface AgentStatus {
  agent_id: string
  status: 'idle' | 'running' | 'connecting' | 'disconnected'
  last_active?: string
  metrics?: {
    total_messages: number
    avg_response_time: number
    success_rate: number
  }
}

export interface AgentDetail extends SessionAgent {
  config?: AgentConfig
  status_detail?: AgentStatus
}

export interface GetAgentConfigParams {
  sessionId: string
  agentId: string
}

export interface UpdateAgentStatusParams {
  sessionId: string
  agentId: string
  status: AgentStatus['status']
}

export const agentApi = {
  /**
   * 获取Agent配置信息
   */
  async getAgentConfig(params: GetAgentConfigParams): Promise<AgentConfig> {
    const { sessionId, agentId } = params
    return request.get(`/session/${sessionId}/agents/${agentId}/config`)
  },

  /**
   * 更新Agent状态
   */
  async updateAgentStatus(params: UpdateAgentStatusParams): Promise<void> {
    const { sessionId, agentId, status } = params
    return request.put(`/session/${sessionId}/agents/${agentId}/status`, { status })
  },

  /**
   * 获取所有Agent配置
   */
  async getAgentConfigs(): Promise<AgentConfig[]> {
    return request.get('/agent/configs')
  },

  /**
   * 获取Agent详情（包含配置和状态）
   */
  async getAgentDetail(sessionId: string, agentId: string): Promise<AgentDetail> {
    const [agent, config] = await Promise.all([
      // 这里需要先获取agent基本信息，暂时使用sessionApi
      Promise.resolve({ agent_id: agentId } as SessionAgent),
      this.getAgentConfig({ sessionId, agentId }).catch(() => null)
    ])
    
    return {
      ...agent,
      config: config || undefined
    }
  }
}

export default agentApi