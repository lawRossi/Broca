import request from '@/utils/request'
import type { Message, MessageType, MessageRole } from './types'

export interface Session {
  session_id: string
  status: string
  description?: string
  workspace?: string
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

export type { Message, MessageType, MessageRole }

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
  provider?: string
  model?: string
}

export interface UpdateSessionParams {
  description?: string
}

export interface CreateSessionResponse {
  session_id: string
  workspace: string
  agent_id: string
  description?: string
  provider?: string
  model?: string
}

export interface SessionStats {
  total_messages: number
  messages_by_type: Record<string, number>
  tool_call_errors: number
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
        keyword: params.keyword,
      },
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
  async getSessionMessages(sessionId: string, skip: number = 0, limit: number = 50): Promise<MessagesResponse> {
    return request.get(`/session/${sessionId}/messages`, {
      params: { skip, limit },
    })
  },

  /**
   * 创建新会话
   */
  async createSession(params: CreateSessionParams = {}): Promise<CreateSessionResponse> {
    return request.post('/session/sessions', params)
  },

  /**
   * 更新会话信息（如描述）
   */
  async updateSession(sessionId: string, params: UpdateSessionParams): Promise<void> {
    return request.put(`/session/${sessionId}`, params)
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
    return request.delete('/session/sessions', { data: { session_ids: sessionIds } })
  },

  /**
   * 获取会话统计信息
   */
  async getSessionStats(sessionId: string): Promise<SessionStats> {
    return request.get(`/session/${sessionId}/stats`)
  },
}

export default sessionApi
