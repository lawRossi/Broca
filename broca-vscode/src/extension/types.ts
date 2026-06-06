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
  | 'connect' | 'disconnect' | 'ping' | 'pong' | 'error'
  | 'user_message' | 'agent_response' | 'agent_error' | 'system_message'
  | 'tool_call'
  | 'task_start' | 'task_complete' | 'task_error'
  | 'turn_start' | 'turn_end'
  | 'subscribe' | 'unsubscribe' | 'broadcast'
  | 'command' | 'command_result'
  | 'permission_request' | 'permission_response'
  | 'agent_query' | 'user_answer'

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

export interface LLMProvider {
  id: string
  name: string
}

export interface LLMModel {
  id: string
  name: string
}

// ==================== Crew (Orchestration) Types ====================

export type OrchestratorType = 'pipeline' | 'supervisor-worker' | 'round-table' | 'broadcast' | 'consensus' | 'composite'

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
  type: 'connected' | 'message' | 'historyLoaded' | 'runnerStatus' | 'sessionStats' | 'session' | 'sessionCreated' | 'error' | 'config' | 'providers' | 'models' | 'saved' | 'agents' | 'runnerActionResult' | 'fileUploaded' | 'commands' | 'tasks' | 'taskDetail' | 'taskCreated' | 'taskUpdated' | 'taskDeleted' | 'taskCommentAdded' | 'jobs' | 'jobDetail' | 'jobExecuted' | 'jobPaused' | 'jobResumed' | 'jobDeleted' | 'crewExecutions' | 'crewDetail' | 'crewEvent' | 'crewConfigs' | 'crewConfigDetail' | 'agentConfig' | 'agentConfigSaved'
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
  type: 'ready' | 'getConfig' | 'sendMessage' | 'loadHistory' | 'respondPermission' | 'respondAgentQuery' | 'redo' | 'abort' | 'undo' | 'uploadFile' | 'runnerAction' | 'fetchRunnerStatus' | 'fetchSessionStats' | 'getSession' | 'fetchAgents' | 'openFile' | 'fetchCommands' | 'fetchTasks' | 'fetchTaskDetail' | 'createTask' | 'updateTask' | 'deleteTask' | 'addTaskComment' | 'fetchJobs' | 'fetchJobDetail' | 'executeJob' | 'pauseJob' | 'resumeJob' | 'deleteJob' | 'fetchCrewExecutions' | 'fetchCrewDetail' | 'submitCrew' | 'abortCrew' | 'deleteCrew' | 'fetchCrewConfigs' | 'fetchCrewConfigDetail' | 'saveCrewConfig' | 'openCrewConfigFile' | 'fetchAgentConfig' | 'updateAgentConfig' | 'fetchLLMProviders' | 'fetchLLMModels'
  payload?: any
}
