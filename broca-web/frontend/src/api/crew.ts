import request from '@/utils/request'

/**
 * 编排器类型
 */
export const OrchestratorType = {
  PIPELINE: 'pipeline',
  SUPERVISOR_WORKER: 'supervisor-worker',
  ROUND_TABLE: 'round-table',
  BROADCAST: 'broadcast',
  CONSENSUS: 'consensus',
  COMPOSITE: 'composite',
} as const

export type OrchestratorType = (typeof OrchestratorType)[keyof typeof OrchestratorType]

/**
 * 执行状态
 */
export const ExecutionStatus = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  ABORTED: 'aborted',
} as const

export type ExecutionStatus = (typeof ExecutionStatus)[keyof typeof ExecutionStatus]

/**
 * Agent 角色配置
 */
export interface AgentRoleConfig {
  role: string
  name: string
  config: string
  extras?: Record<string, any>
}

/**
 * 编排器配置
 */
export interface OrchestratorConfig {
  type: OrchestratorType
  max_rounds?: number
  strategy?: string
  threshold?: number
  weights?: Record<string, number>
}

/**
 * Crew 配置
 */
export interface CrewConfig {
  name: string
  description: string
  orchestrator: OrchestratorConfig
  agents: AgentRoleConfig[]
  blackboard?: {
    initial_entries?: Array<{ key: string; value: any }>
  }
  sub_crews?: Array<{
    name: string
    orchestrator: OrchestratorConfig
    steps?: Array<{ agent: string; task: string }>
  }>
}

/**
 * 阶段结果
 */
export interface PhaseResult {
  name: string
  status: string
  agents: string[]
  output?: Record<string, any>
  error?: string
  started_at?: string
  completed_at?: string
}

/**
 * 编排执行记录
 */
export interface CrewExecution {
  execution_id: string
  session_id: string
  crew_name: string
  description: string
  orchestrator_type: OrchestratorType
  agent_count: number
  status: ExecutionStatus
  error?: string
  result?: Record<string, any>
  phases?: PhaseResult[]
  created_at: string
  completed_at?: string
}

/**
 * 提交编排请求
 */
export interface CrewSubmitRequest {
  yaml_content?: string
  yaml_path?: string
  session_id: string
}

/**
 * 校验编排请求
 */
export interface CrewValidateRequest {
  yaml_content?: string
  yaml_path?: string
}

/**
 * 校验结果
 */
export interface CrewValidateResult {
  valid: boolean
  errors: string[]
  error_count: number
}

/**
 * 编排列表响应
 */
export interface CrewListResponse {
  executions: CrewExecution[]
  total: number
}

/**
 * Crew API
 */
export const crewApi = {
  /**
   * 提交编排执行
   */
  async submit(data: CrewSubmitRequest): Promise<CrewExecution> {
    return request.post('/crews', data)
  },

  /**
   * 校验编排配置
   */
  async validate(data: CrewValidateRequest): Promise<CrewValidateResult> {
    return request.post('/crews/validate', data)
  },

  /**
   * 获取编排执行列表
   */
  async list(params?: {
    session_id?: string
    status?: string
  }): Promise<CrewListResponse> {
    return request.get('/crews', { params })
  },

  /**
   * 获取编排执行详情
   */
  async getDetail(executionId: string): Promise<CrewExecution> {
    return request.get(`/crews/${executionId}`)
  },

  /**
   * 中止编排执行
   */
  async abort(executionId: string): Promise<{ execution_id: string }> {
    return request.post(`/crews/${executionId}/abort`)
  },
}

export default crewApi
