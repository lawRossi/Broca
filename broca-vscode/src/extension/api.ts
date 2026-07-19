import axios, { type AxiosInstance } from 'axios'
import type { ConfigManager } from './config'
import type {
  Session,
  SessionsResponse,
  CreateSessionParams,
  CreateSessionResponse,
  UpdateSessionParams,
  RunnerInfo,
  Agent,
  AgentConfig,
  SessionStats,
  MessagesResponse,
  TurnsResponse,
  LLMProvider,
  LLMModel,
  CrewExecution,
  CrewConfigFile,
  CrewConfigDetail,
  CommandInfo,
  SearchParams,
  SearchFilters,
  SearchMessagesResponse,
} from './types'

export class ApiClient {
  public client: AxiosInstance
  private getToken: () => string | null

  /**
   * Callback invoked when a 401 (Unauthorized) response is received.
   * Typically wired to AuthManager.handleAuthError() for automatic logout + login prompt.
   */
  onAuthError: (() => void) | null = null

  constructor(configManager: ConfigManager, getToken: () => string | null) {
    this.getToken = getToken
    this.client = axios.create({
      baseURL: `${configManager.serverUrl}/api`,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // Request interceptor to add auth token
    this.client.interceptors.request.use((config) => {
      const token = this.getToken()
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
      return config
    })

    // Response interceptor: unwrap ApiResponse { code, data, msg } → modify response.data in place
    this.client.interceptors.response.use(
      (response) => {
        const body = response.data
        // If the backend wraps in { code: 200, data: { ... }, msg: "..." }
        if (body && typeof body === 'object' && 'code' in body) {
          if (body.code === 200) {
            response.data = body.data // replace response.data with inner data
            return response
          } else {
            return Promise.reject(new Error(body.msg || 'Request failed'))
          }
        }
        return response // fallback: return as-is
      },
      (error) => {
        if (error.response?.status === 401) {
          const requestUrl = error.config?.url || ''
          // Skip onAuthError for login endpoint — 401 there means wrong credentials, not expired token
          const isLoginRequest = requestUrl.endsWith('/auth/login')
          if (isLoginRequest) {
            console.error('Login failed: invalid credentials (401)')
          } else {
            console.error('Authentication failed: token may be expired, triggering auto-logout')
            // Call the auth error handler — will clear session and show login prompt
            this.onAuthError?.()
          }
        }
        return Promise.reject(error)
      }
    )
  }

  // ==================== Session API ====================

  async getSessions(params?: { skip?: number; limit?: number; keyword?: string }): Promise<SessionsResponse> {
    const response = await this.client.get('/session/sessions', {
      params: {
        skip: params?.skip ?? 0,
        limit: params?.limit ?? 50,
        keyword: params?.keyword,
      },
    })
    return response.data
  }

  async getSession(sessionId: string): Promise<Session> {
    const response = await this.client.get(`/session/${sessionId}`)
    return response.data
  }

  async createSession(params: CreateSessionParams = {}): Promise<CreateSessionResponse> {
    const response = await this.client.post('/session/sessions', params)
    return response.data
  }

  async updateSession(sessionId: string, params: UpdateSessionParams): Promise<void> {
    await this.client.put(`/session/${sessionId}`, params)
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.client.delete(`/session/${sessionId}`)
  }

  async deleteSessions(sessionIds: string[]): Promise<void> {
    await this.client.delete('/session/sessions', { data: { session_ids: sessionIds } })
  }

  // ==================== Runner API ====================

  async getRunnerStatus(sessionId: string): Promise<RunnerInfo> {
    const response = await this.client.get(`/session/${sessionId}/runner/status`)
    return response.data
  }

  async restartRunner(sessionId: string): Promise<{ session_id: string; pid: number; status: string }> {
    const response = await this.client.post(`/session/${sessionId}/runner/restart`)
    return response.data
  }

  async stopRunner(sessionId: string): Promise<void> {
    await this.client.post(`/session/${sessionId}/runner/stop`)
  }

  // ==================== Agent API ====================

  async getSessionAgents(sessionId: string): Promise<Agent[]> {
    const response = await this.client.get(`/session/${sessionId}/agents`)
    return response.data
  }

  async getAgentConfig(sessionId: string, agentId: string): Promise<AgentConfig> {
    const response = await this.client.get(`/session/${sessionId}/agents/${agentId}/config`)
    return response.data
  }

  async updateAgentConfig(
    sessionId: string,
    agentId: string,
    configContent: Record<string, any>
  ): Promise<AgentConfig> {
    const response = await this.client.put(`/session/${sessionId}/agents/${agentId}/config`, {
      config_content: configContent,
    })
    return response.data
  }

  // ==================== Stats API ====================

  async getSessionStats(sessionId: string): Promise<SessionStats> {
    const response = await this.client.get(`/session/${sessionId}/stats`)
    return response.data
  }

  // ==================== Message API ====================

  async getSessionMessages(
    sessionId: string,
    skip: number = 0,
    limit: number = 50,
    executionId?: string
  ): Promise<MessagesResponse> {
    const params: Record<string, any> = { skip, limit }
    if (executionId) {
      params.execution_id = executionId
    }
    const response = await this.client.get(`/session/${sessionId}/messages`, { params })
    return response.data
  }

  // ==================== Turns (Concise Mode) API ====================

  async getSessionTurns(
    sessionId: string,
    skip: number = 0,
    limit: number = 3,
    executionId?: string
  ): Promise<TurnsResponse> {
    const params: Record<string, any> = { skip, limit }
    if (executionId) {
      params.execution_id = executionId
    }
    const response = await this.client.get(`/session/${sessionId}/turns`, {
      params,
    })
    return response.data
  }

  async getFileDiff(sessionId: string, turnId: string, path: string): Promise<{ diff: string; file_path: string }> {
    const response = await this.client.get(`/session/${sessionId}/turns/${turnId}/file-diff`, {
      params: { path },
    })
    return response.data
  }

  // ==================== Auth API ====================

  async login(username: string, password: string): Promise<{ token: string; user_id: string; username: string }> {
    const response = await this.client.post('/auth/login', { username, password })
    return response.data
  }

  /** 本地自动登录（仅对本机部署生效） */
  async localLogin(): Promise<{ token: string; user_id: string; username: string }> {
    const response = await this.client.post('/auth/local-login')
    return response.data
  }

  // 注册功能已移除：请在安装时通过 scripts/setup_admin.py 创建账户

  // ==================== Config API ====================

  async getLLMProviders(): Promise<LLMProvider[]> {
    const response = await this.client.get('/config/llm/providers')
    return response.data
  }

  async getLLMModels(provider: string): Promise<LLMModel[]> {
    const response = await this.client.get(`/config/llm/models/${provider}`)
    return response.data
  }

  // ==================== Commands API ====================

  async getCommands(): Promise<CommandInfo[]> {
    const response = await this.client.get('/commands')
    return response.data.commands || response.data
  }

  // ==================== Crew (Orchestration) API ====================

  async submitCrew(data: { yaml_content?: string; yaml_path?: string; session_id: string }): Promise<CrewExecution> {
    const response = await this.client.post('/crews', data)
    return response.data
  }

  async validateCrew(data: {
    yaml_content?: string
    yaml_path?: string
  }): Promise<{ valid: boolean; errors: string[]; error_count: number }> {
    const response = await this.client.post('/crews/validate', data)
    return response.data
  }

  async getCrews(params?: {
    session_id?: string
    status?: string
  }): Promise<{ executions: CrewExecution[]; total: number }> {
    const response = await this.client.get('/crews', { params })
    return response.data
  }

  async getCrewDetail(executionId: string): Promise<CrewExecution> {
    const response = await this.client.get(`/crews/${executionId}`)
    return response.data
  }

  async abortCrew(executionId: string): Promise<{ execution_id: string }> {
    const response = await this.client.post(`/crews/${executionId}/abort`)
    return response.data
  }

  async deleteCrew(executionId: string): Promise<{ execution_id: string }> {
    const response = await this.client.delete(`/crews/${executionId}`)
    return response.data
  }

  async listCrewConfigs(workspace: string): Promise<{ configs: CrewConfigFile[]; total: number }> {
    const response = await this.client.get('/crews/configs', { params: { workspace } })
    return response.data
  }

  async getCrewConfig(filename: string, workspace: string): Promise<CrewConfigDetail> {
    const response = await this.client.get(`/crews/configs/${encodeURIComponent(filename)}`, {
      params: { workspace },
    })
    return response.data
  }

  async saveCrewConfig(filename: string, workspace: string, content: string): Promise<CrewConfigFile> {
    const response = await this.client.put(`/crews/configs/${encodeURIComponent(filename)}`, {
      workspace,
      filename,
      content,
    })
    return response.data
  }

  // ==================== Search API ====================

  async searchSessionMessages(sessionId: string, params?: SearchParams): Promise<SearchMessagesResponse> {
    const response = await this.client.get(`/session/${sessionId}/messages/search`, {
      params: {
        keyword: params?.keyword,
        message_type: params?.message_type,
        sender_id: params?.sender_id,
        tool_name: params?.tool_name,
        order: params?.order ?? 'desc',
        skip: params?.skip ?? 0,
        limit: params?.limit ?? 20,
      },
    })
    return response.data
  }

  async getSearchFilters(sessionId: string): Promise<SearchFilters> {
    const response = await this.client.get(`/session/${sessionId}/messages/search/filters`)
    return response.data
  }
}
