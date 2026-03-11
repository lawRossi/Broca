import request from '@/utils/request'

export interface Session {
  session_id: string
  status: string
  description?: string
  created_at: string
  finished_at?: string
}

export interface Agent {
  agent_id: string
  config_id: string
  session_id: string
  name?: string
  role?: string
  created_at: string
  type?: string
  status?: string
  description?: string
}

export interface Message {
  message_id: string
  session_id: string
  turn_id: string
  agent_id: string
  role: string
  content?: string
  message_type: string
  sequence_number: number
  timestamp: string
}

export interface Turn {
  turn_id: string
  session_id: string
  agent_id: string
  sequence_number: number
  turn_description?: string
  created_at: string
}

export interface LatestAgentResponse {
  agent_id: string
  agent_name: string
  has_agents: boolean
}

export interface MessagesResponse {
  messages: Message[]
  total: number
  skip: number
  limit: number
}

export interface TurnsResponse {
  turns: Turn[]
  total: number
  skip: number
  limit: number
}

export interface SessionsResponse {
  sessions: Session[]
  total: number
  skip: number
  limit: number
}

export interface SessionQueryParams {
  skip?: number
  limit?: number
  status?: string
  keyword?: string
}

export interface CreateSessionParams {
  description?: string
  workspace?: string
}

export interface CreateSessionResponse {
  session_id: string
  workspace: string
  agent_id: string
  description?: string
}

export const sessionApi = {
  /**
   * 获取会话列表
   */
  async getSessions(params: SessionQueryParams = {}): Promise<SessionsResponse> {
    return request.get('/session/sessions', {
      params: {
        skip: params.skip ?? 0,
        limit: params.limit ?? 20,
        status: params.status,
        keyword: params.keyword
      }
    })
  },

  /**
   * 获取会话的Agent列表
   */
  async getSessionAgents(sessionId: string): Promise<Agent[]> {
    return request.get(`/session/${sessionId}/agents`)
  },

  /**
   * 获取会话的消息历史
   */
  async getSessionMessages(
    sessionId: string,
    skip: number = 0,
    limit: number = 50
  ): Promise<MessagesResponse> {
    return request.get(`/session/${sessionId}/messages`, {
      params: { skip, limit }
    })
  },

  /**
   * 获取会话的轮次
   */
  async getSessionTurns(
    sessionId: string,
    skip: number = 0,
    limit: number = 100
  ): Promise<TurnsResponse> {
    return request.get(`/session/${sessionId}/turns`, {
      params: { skip, limit }
    })
  },

  /**
   * 获取会话的最新Agent（用于自动获取agent_id）
   */
  async getSessionLatestAgent(sessionId: string): Promise<LatestAgentResponse> {
    return request.get(`/session/${sessionId}/latest-agent`)
  },

  /**
   * 创建新会话
   */
  async createSession(params: CreateSessionParams = {}): Promise<CreateSessionResponse> {
    return request.post('/session/sessions', params)
  },

  /**
   * 删除单个会话
   */
  async deleteSession(sessionId: string): Promise<void> {
    return request.delete(`/session/${sessionId}`)
  },

  /**
   * 批量删除会话
   */
  async deleteSessions(sessionIds: string[]): Promise<void> {
    return request.delete('/session/sessions', {
      data: { session_ids: sessionIds }
    })
  }
}

export default sessionApi