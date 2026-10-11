// WebView-side types (mirrors extension/types.ts)

export type MessageType =
  | 'agent_system_message'
  | 'connect'
  | 'disconnect'
  | 'ping'
  | 'pong'
  | 'error'
  | 'user_message'
  | 'agent_response'
  | 'agent_error'
  | 'system_message'
  | 'tool_call'
  | 'task_start'
  | 'task_complete'
  | 'task_error'
  | 'turn_start'
  | 'turn_end'
  | 'step_start'
  | 'step_end'
  | 'reasoning_content'
  | 'subscribe'
  | 'unsubscribe'
  | 'broadcast'
  | 'command'
  | 'command_result'
  | 'permission_request'
  | 'permission_response'
  | 'agent_query'
  | 'user_answer'

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool' | 'agent_system' | 'agent'

export interface Message {
  message_id: string
  message_type: MessageType
  timestamp: string
  role: MessageRole
  data: Record<string, any>
  sender_id?: string
  receiver_id?: string
  room?: string
  subscription?: string
  session_id?: string
  turn_id?: string
  agent_id?: string
  sequence_number?: number
}

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

export interface SessionStats {
  total_messages: number
  messages_by_type: Record<string, number>
  tool_call_errors: number
}

export interface LLMProvider {
  id: string
  name: string
}

export interface LLMModel {
  id: string
  name: string
}

// ==================== Config Types (aligned with broca-web/frontend/src/api/config.ts) ====================

/** 模型元信息（modality、上下文窗口等） */
export interface LLMModelMeta {
  modality?: Record<string, unknown>
  context_window?: number
  [key: string]: unknown
}

/** 单个模型配置 */
export interface LLMModelConfig {
  model: string
  temperature?: number
  max_tokens?: number
  extra_body?: Record<string, unknown>
  reasoning_effort?: string
  allowed_openai_params?: string[]
  meta?: LLMModelMeta
  [key: string]: unknown
}

/** 单个提供商配置 */
export interface LLMProviderConfig {
  base_url: string
  api_key: string
  models: Record<string, LLMModelConfig>
  [key: string]: unknown
}

/** 完整 LLM 配置：provider id → 提供商配置 */
export type LLMConfig = Record<string, LLMProviderConfig>

/** ASR 语音识别配置 */
export interface ASRConfig {
  model_name?: string
  decoding_method?: string
  noise_gate_rms?: number
}

/** 基础配置（configs.json） */
export interface GeneralConfig {
  database_dir?: string
  log_file?: string
  log_level?: string
  llm_config_file?: string
  socket_server_url?: string
  api_server_url?: string
  execution?: ExecutionConfig
  asr?: ASRConfig
}

/** 执行引擎配置 */
export interface ExecutionConfig {
  step_max_errors?: number
  llm_retry_delay?: number
  tool_call_timeout?: number
  assign_task_timeout?: number
  llm_timeout?: number
  llm_first_chunk_timeout?: number
  dead_loop_window?: number
  message_queue_size?: number
  permission_request_timeout?: number
  agent_query_timeout?: number
}

/** 工具权限配置 */
export interface ToolPermissionConfig {
  _description?: string
  _permission_values?: Record<string, string>
  tools: Record<string, string>
}

/** 合法权限值 */
export const PERMISSION_VALUES = ['allow', 'ask', 'forbidden'] as const
export type PermissionValue = (typeof PERMISSION_VALUES)[number]

/** 合法日志级别 */
export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

/** 单个 MCP 服务器配置 */
export interface McpServerConfig {
  command?: string
  args?: string[]
  env?: Record<string, string>
  cwd?: string
  url?: string
  headers?: Record<string, string>
  tool_timeout?: number
  [key: string]: unknown
}

/** 完整 MCP 配置：服务器名 → 服务器配置 */
export type McpConfig = Record<string, McpServerConfig>

/** MCP 传输类型 */
export const MCP_TRANSPORTS = ['stdio', 'http'] as const
export type McpTransport = (typeof MCP_TRANSPORTS)[number]

// ==================== Crew (Orchestration) Types ====================

export type OrchestratorType =
  'pipeline' | 'supervisor-worker' | 'round-table' | 'broadcast' | 'consensus' | 'composite'

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'aborted'

export interface PhaseResult {
  name: string
  status: string
  agents: string[]
  output?: Record<string, any>
  error?: string
  started_at?: string
  completed_at?: string
}

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
  phases_total?: number
  progress?: number
  created_at: string
  completed_at?: string
}

export interface CrewConfigFile {
  filename: string
  path: string
  name: string
  description: string
  orchestrator_type: string | null
  agent_count: number
  agent_names: string[]
  modified_time: number
  parse_error?: string
}

export interface CrewConfigDetail {
  filename: string
  path: string
  content: string
  summary: {
    name?: string
    description?: string
    orchestrator_type?: string | null
    agent_count?: number
    agent_names?: string[]
    parse_error?: string
  }
  modified_time: number
}

// ==================== Task Types ====================

export type TaskStatus = 'pending' | 'in_progress' | 'blocked' | 'completed'
export type TaskPriority = 'low' | 'medium' | 'high'

export interface Task {
  task_id: string
  name: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  assignee?: string
  parent_id?: string
  session_id?: string
  details?: string
  acceptance_criteria?: string[]
  context_files?: string[]
  context_links?: string[]
  context_notes?: string
  report?: string
  dependencies?: string[]
  created_at: string
  updated_at: string
}

export interface TaskDetail {
  task: Task
  comments: TaskComment[]
  children: ChildTask[]
}

export interface TaskComment {
  comment_id: string
  author: string
  content: string
  created_at: string
}

export interface ChildTask {
  task_id: string
  name: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  assignee?: string
  created_at: string
  updated_at: string
}

// ==================== Job (Cron) Types ====================

export type JobType = 'reminder' | 'command'
export type JobStatus = 'active' | 'paused' | 'completed' | 'cancelled'
export type TriggerType = 'cron' | 'interval' | 'date'

export interface Job {
  job_id: string
  name: string
  job_type: JobType
  status: JobStatus
  trigger_type: TriggerType
  trigger_config: Record<string, any>
  content: string
  session_id?: string
  agent_id?: string
  created_at: string
  updated_at: string
  next_run_time?: string
}

export interface JobExecution {
  execution_id: string
  executed_at: string
  success: boolean
  result?: string
}

export interface JobDetail {
  job: Job
  executions: JobExecution[]
}
