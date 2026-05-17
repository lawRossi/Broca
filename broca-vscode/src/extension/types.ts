// Shared types between Extension Host and WebView

export interface Session {
  session_id: string
  description?: string
  workspace?: string
  created_at: string
  finished_at?: string
  runner_status?: string
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

// WebView ↔ Extension Host communication protocol
export interface WebViewMessage {
  type: string
  payload?: any
}

// Extension → WebView messages
export interface ExtensionToWebView {
  type: 'connected' | 'message' | 'historyLoaded' | 'runnerStatus' | 'sessionStats' | 'sessionCreated' | 'error' | 'config' | 'providers' | 'models' | 'saved' | 'agents' | 'runnerActionResult' | 'fileUploaded' | 'tasks' | 'taskDetail' | 'taskCreated' | 'taskUpdated' | 'taskDeleted' | 'taskCommentAdded' | 'jobs' | 'jobDetail' | 'jobExecuted' | 'jobPaused' | 'jobResumed' | 'jobDeleted'
  payload: any
}

// WebView → Extension messages
export interface WebViewToExtension {
  type: 'ready' | 'getConfig' | 'sendMessage' | 'loadHistory' | 'respondPermission' | 'respondAgentQuery' | 'redo' | 'abort' | 'undo' | 'uploadFile' | 'runnerAction' | 'fetchRunnerStatus' | 'fetchSessionStats' | 'fetchAgents' | 'openFile' | 'fetchTasks' | 'fetchTaskDetail' | 'createTask' | 'updateTask' | 'deleteTask' | 'addTaskComment' | 'fetchJobs' | 'fetchJobDetail' | 'executeJob' | 'pauseJob' | 'resumeJob' | 'deleteJob'
  payload?: any
}
