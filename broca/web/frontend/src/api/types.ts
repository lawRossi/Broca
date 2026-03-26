// 与后端session.models.py中的MessageType保持一致
export type MessageType =
  // 系统消息
  | 'agent_system_message'
  | 'connect'
  | 'disconnect'
  | 'ping'
  | 'pong'
  | 'error'
  // 用户交互消息
  | 'user_message'
  | 'agent_response'
  | 'agent_error'
  | 'system_message'
  // 工具执行
  | 'tool_call'
  // 任务管理
  | 'task_start'
  | 'task_complete'
  | 'task_error'
  // 轮次管理
  | 'turn_start'
  | 'turn_end'
  // 订阅和广播
  | 'subscribe'
  | 'unsubscribe'
  | 'broadcast'
  // 命令消息
  | 'command'
  | 'command_result'
  // 权限消息
  | 'permission_request'
  | 'permission_response'
  // 用户问答消息
  | 'agent_query'
  | 'user_answer'

// 与后端session.models.py中的MessageRole保持一致
export type MessageRole =
  | 'user'
  | 'assistant'
  | 'system'
  | 'tool'
  | 'agent_system'
  | 'agent'

// 统一的Message接口，与后端session.models.py中的Message模型完全对应
export interface Message {
  // 基础字段（必需）
  message_id: string
  message_type: MessageType
  timestamp: string
  role: MessageRole
  data: Record<string, any>
  
  // 通信字段（可选）
  sender_id?: string
  receiver_id?: string
  room?: string
  subscription?: string
  
  // 会话关联字段（可选）
  session_id?: string
  turn_id?: string
  agent_id?: string
  
  // 序列号（可选）
  sequence_number?: number
}