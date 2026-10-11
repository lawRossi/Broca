// Shared types between Extension Host and WebView

export interface Session {
  session_id: string
  description?: string
  workspace?: string
  created_at: string
  finished_at?: string
  runner_status?: string
  category?: 'normal' | 'agent-orchestration'
}

export interface CreateSessionParams {
  description?: string
  workspace?: string
  provider?: string
  model?: string
  category?: 'normal' | 'agent-orchestration'
}

export interface UpdateSessionParams {
  description?: string
}

export interface SessionsResponse {
  sessions: Session[]
  total: number
  skip: number
  limit: number
}

export interface CreateSessionResponse {
  session_id: string
  workspace: string
  agent_id: string
  description?: string
  provider?: string
  model?: string
  category?: string
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

// Message types (matching backend session.models.py)
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

export interface MessagesResponse {
  messages: Message[]
  total: number
  skip: number
  limit: number
}

export interface TurnSummaryData {
  turn_id: string
  sequence_number: number
  agent_id: string
  agent_name: string
  user_message: string | null
  status: string
  current_tool: string | null
  current_file_path: string | null
  current_todo_list: Array<{ name: string; status: string }>
  total_duration: number
  total_steps: number
  tool_call_stats: Array<{ tool_name: string; count: number }>
  final_response: string
  reasoning_content: string
  is_active: boolean
  started_at: string
  created_at: string
  last_message_id: string | null
  changed_files?: {
    total_added: number
    total_deleted: number
    total_modified: number
    files_added: string[]
    files_deleted: string[]
    files_modified: string[]
  }
}

export interface TurnsResponse {
  turns: TurnSummaryData[]
  total: number
  skip: number
  limit: number
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

// ==================== Search Types ====================

export interface SearchFilters {
  tool_names: string[]
}

export interface SearchParams {
  keyword?: string
  message_type?: string
  sender_id?: string
  tool_name?: string
  order?: 'desc' | 'asc'
  skip?: number
  limit?: number
}

export interface SearchMessagesResponse {
  messages: Message[]
  total: number
  skip: number
  limit: number
}

// ==================== Command Types ====================

export interface CommandInfo {
  name: string
  description: string
  type: string
  argument_hint: string
}

export interface CommandsResponse {
  commands: CommandInfo[]
}

// WebView ↔ Extension Host communication protocol
export interface WebViewMessage {
  type: string
  payload?: any
}

// Extension → WebView messages
export interface ExtensionToWebView {
  type:
    | 'connected'
    | 'message'
    | 'historyLoaded'
    | 'runnerStatus'
    | 'sessionStats'
    | 'session'
    | 'sessionCreated'
    | 'error'
    | 'config'
    | 'providers'
    | 'models'
    | 'saved'
    | 'agents'
    | 'runnerActionResult'
    | 'fileUploaded'
    | 'commands'
    | 'tasks'
    | 'taskDetail'
    | 'taskCreated'
    | 'taskUpdated'
    | 'taskDeleted'
    | 'taskCommentAdded'
    | 'jobs'
    | 'jobDetail'
    | 'jobExecuted'
    | 'jobPaused'
    | 'jobResumed'
    | 'jobDeleted'
    | 'crewExecutions'
    | 'crewDetail'
    | 'crewEvent'
    | 'crewConfigs'
    | 'crewConfigDetail'
    | 'agentConfig'
    | 'agentConfigSaved'
    | 'turnsData'
    | 'searchMessages'
    | 'searchFilters'
    | 'fileDiffResult'
    | 'workspacePath'
    | 'refreshSession'
    | 'files'
    | 'asrEvent'
    | 'voiceInputStopped'
    | 'voiceInputSupported'
    | 'generalConfig'
    | 'generalConfigSaved'
    | 'generalConfigError'
    | 'llmConfig'
    | 'llmConfigSaved'
    | 'llmConfigError'
    | 'toolPermission'
    | 'toolPermissionSaved'
    | 'toolPermissionError'
    | 'mcpConfig'
    | 'mcpSaved'
    | 'mcpError'
  payload: any
}

// Agent Config
export interface AgentConfig {
  agent_id: string
  agent_name: string
  agent_role: string
  config_id: string
  config_name: string
  config_content: Record<string, any>
  created_at?: string
}

// WebView → Extension messages
export interface WebViewToExtension {
  type:
    | 'ready'
    | 'getConfig'
    | 'sendMessage'
    | 'loadHistory'
    | 'respondPermission'
    | 'respondAgentQuery'
    | 'redo'
    | 'abort'
    | 'undo'
    | 'uploadFile'
    | 'runnerAction'
    | 'fetchRunnerStatus'
    | 'fetchSessionStats'
    | 'getSession'
    | 'fetchAgents'
    | 'openFile'
    | 'fetchCommands'
    | 'fetchTasks'
    | 'fetchTaskDetail'
    | 'createTask'
    | 'updateTask'
    | 'deleteTask'
    | 'addTaskComment'
    | 'fetchJobs'
    | 'fetchJobDetail'
    | 'executeJob'
    | 'pauseJob'
    | 'resumeJob'
    | 'deleteJob'
    | 'fetchCrewExecutions'
    | 'fetchCrewDetail'
    | 'submitCrew'
    | 'abortCrew'
    | 'deleteCrew'
    | 'fetchCrewConfigs'
    | 'fetchCrewConfigDetail'
    | 'saveCrewConfig'
    | 'openCrewConfigFile'
    | 'fetchAgentConfig'
    | 'updateAgentConfig'
    | 'fetchLLMProviders'
    | 'fetchLLMModels'
    | 'fetchTurns'
    | 'searchMessages'
    | 'getSearchFilters'
    | 'listFiles'
    | 'startVoiceInput'
    | 'stopVoiceInput'
    | 'checkVoiceInput'
    | 'getGeneralConfig'
    | 'saveGeneralConfig'
    | 'getLLMConfig'
    | 'saveLLMConfig'
    | 'getToolPermissionConfig'
    | 'saveToolPermissionConfig'
    | 'getMcpConfig'
    | 'saveMcpConfig'
  payload?: any
}
