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
  SessionStats,
  MessagesResponse,
  LLMProvider,
  LLMModel,
} from './types'

export class ApiClient {
  public client: AxiosInstance
  private getToken: () => string | null

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
            response.data = body.data  // replace response.data with inner data
            return response
          } else {
            return Promise.reject(new Error(body.msg || 'Request failed'))
          }
        }
        return response // fallback: return as-is
      },
      (error) => {
        if (error.response?.status === 401) {
          console.error('Authentication failed: token may be expired')
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

  // ==================== Stats API ====================

  async getSessionStats(sessionId: string): Promise<SessionStats> {
    const response = await this.client.get(`/session/${sessionId}/stats`)
    return response.data
  }

  // ==================== Message API ====================

  async getSessionMessages(sessionId: string, skip: number = 0, limit: number = 50): Promise<MessagesResponse> {
    const response = await this.client.get(`/session/${sessionId}/messages`, {
      params: { skip, limit },
    })
    return response.data
  }

  // ==================== Config API ====================

  async getLLMProviders(): Promise<LLMProvider[]> {
    const response = await this.client.get('/config/llm/providers')
    return response.data
  }

  async getLLMModels(provider: string): Promise<LLMModel[]> {
    const response = await this.client.get(`/config/llm/models/${provider}`)
    return response.data
  }
}
