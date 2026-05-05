// WebView-side types (mirrors extension/types.ts)

export type MessageType =
  | 'agent_system_message' | 'connect' | 'disconnect' | 'ping' | 'pong' | 'error'
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

export interface LLMProvider {
  id: string
  name: string
}

export interface LLMModel {
  id: string
  name: string
}
