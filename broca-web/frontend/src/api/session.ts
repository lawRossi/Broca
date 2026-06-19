import request from '@/utils/request'
import type { Message, MessageType, MessageRole } from './types'

export interface Session {
  session_id: string
  description?: string
  workspace?: string
  created_at: string
  finished_at?: string
  category?: string                // 会话分类：normal / agent-orchestration
  runner_status?: string           // Runner 进程状态（由后端从 SessionRunner 表获取）
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
  keyword?: string
}

export interface CreateSessionParams {
  description?: string
  workspace?: string
  provider?: string
  model?: string
  category?: string
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

export interface TurnSummaryData {
  turn_id: string
  sequence_number: number
  agent_id: string
  agent_name: string | null
  started_at: string | null
  ended_at: string | null
  duration_seconds: number | null
  created_at: string | null
  // 后端计算的统计数据
  user_message: string | null
  total_steps: number
  tool_call_stats: Array<{ tool_name: string; count: number }>
  current_file_path: string | null
  current_todo_list: Array<{ name: string; status: string }>
  final_response: string
  is_reverted: boolean
  last_message_id: string | null
}

export interface TurnsResponse {
  turns: TurnSummaryData[]
  total: number
  skip: number
  limit: number
}

// 新增：Runner 状态接口
export interface RunnerInfo {
  session_id: string
  pid: number | null
  status: string
  started_at: string | null
  ipc_address: string
  resource_usage: Record<string, any>
  last_heartbeat: string | null
  restart_count: number
  error_message: string | null
  uptime_seconds: number
}

export interface RunnerStats {
  total_runners: number
  max_concurrent: number
  available_slots: number
  by_status: Record<string, number>
  runners: RunnerInfo[]
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
        keyword: params.keyword,
      },
    })
  },

  /**
   * 获取单个会话详情
   */
  async getSession(sessionId: string): Promise<Session> {
    return request.get(`/session/${sessionId}`)
  },

  /**
   * 获取会话的Agent列表
   */
  async getSessionAgents(sessionId: string): Promise<Agent[]> {
    return request.get(`/session/${sessionId}/agents`)
  },

  /**
   * 获取会话的消息历史
   * @param executionId - 可选，按编排执行ID过滤
   */
  async getSessionMessages(sessionId: string, skip: number = 0, limit: number = 50, executionId?: string): Promise<MessagesResponse> {
    const params: Record<string, any> = { skip, limit }
    if (executionId) {
      params.execution_id = executionId
    }
    return request.get(`/session/${sessionId}/messages`, { params })
  },

  /**
   * 搜索会话中的消息
   */
  async searchSessionMessages(
    sessionId: string,
    params: {
      keyword?: string
      message_type?: string
      sender_id?: string
      tool_name?: string
      order?: string
      skip?: number
      limit?: number
    } = {}
  ): Promise<MessagesResponse> {
    return request.get(`/session/${sessionId}/messages/search`, { params })
  },

  /**
   * 获取搜索筛选选项
   */
  async getSearchFilters(sessionId: string): Promise<{ tool_names: string[] }> {
    return request.get(`/session/${sessionId}/messages/search/filters`)
  },

  /**
   * 创建新会话
   */
  async createSession(params: CreateSessionParams = {}, silent = false): Promise<CreateSessionResponse> {
    const config = silent ? { silent: true as any } : undefined
    return request.post('/session/sessions', params, config)
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

  /**
   * 获取会话的 turn 摘要列表（简洁模式使用）
   */
  async getSessionTurns(
    sessionId: string,
    skip: number = 0,
    limit: number = 20,
    executionId?: string
  ): Promise<TurnsResponse> {
    const params: Record<string, any> = { skip, limit }
    if (executionId) {
      params.execution_id = executionId
    }
    return request.get(`/session/${sessionId}/turns`, { params })
  },

  /**
   * 获取 turn 中指定文件的 unified diff
   */
  async getFileDiff(
    sessionId: string,
    turnId: string,
    path: string
  ): Promise<{ diff: string; file_path: string }> {
    return request.get(`/session/${sessionId}/turns/${turnId}/file-diff`, {
      params: { path },
    })
  },

  // ==================== Runner 管理 API ====================

  /**
   * 获取所有 Runner 进程列表
   */
  async getRunners(): Promise<RunnerStats> {
    return request.get('/session/runners')
  },

  /**
   * 获取 Runner 统计
   */
  async getRunnerStats(): Promise<RunnerStats> {
    return request.get('/session/runners/stats')
  },

  /**
   * 获取单个 Session 的 Runner 状态
   */
  async getRunnerStatus(sessionId: string): Promise<RunnerInfo> {
    return request.get(`/session/${sessionId}/runner/status`)
  },

  /**
   * 重启 Runner 进程
   */
  async restartRunner(sessionId: string): Promise<{ session_id: string; pid: number; status: string }> {
    return request.post(`/session/${sessionId}/runner/restart`)
  },

  /**
   * 停止 Runner 进程
   */
  async stopRunner(sessionId: string): Promise<void> {
    return request.post(`/session/${sessionId}/runner/stop`)
  },
}

export default sessionApi
