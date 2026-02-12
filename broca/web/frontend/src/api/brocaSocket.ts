// Lightweight Socket.IO client wrapper for Broca protocol.
//
// NOTE: We intentionally avoid adding socket.io-client dependency right now.
// This file is a placeholder and will be wired once dependency installation is resolved.
//
// The intended implementation mirrors Broca/comm/socketio_client.py:
// - listen on 'message'
// - parse Message
// - dispatch by message_type (agent_response/turn_start/permission_request...)

export type BrocaMessageType =
  | 'connect'
  | 'disconnect'
  | 'ping'
  | 'pong'
  | 'error'
  | 'user_message'
  | 'agent_response'
  | 'agent_thinking'
  | 'agent_error'
  | 'task_start'
  | 'task_progress'
  | 'task_complete'
  | 'task_failed'
  | 'turn_start'
  | 'turn_end'
  | 'tool_call'
  | 'tool_result'
  | 'subscribe'
  | 'unsubscribe'
  | 'broadcast'
  | 'command'
  | 'command_result'
  | 'permission_request'
  | 'permission_response'

export interface BrocaMessage {
  message_id: string
  message_type: BrocaMessageType
  timestamp: string
  sub_type?: string
  status?: number
  sender_id?: string
  receiver_id?: string
  room?: string
  subscription?: string
  data?: Record<string, any>
  metadata?: Record<string, any>
  error_code?: string
  error_message?: string
}

export interface BrocaConnectionOptions {
  serverUrl: string
  clientType: string
  clientId: string
  userId?: string
}

export type BrocaEventName = 'connect' | 'disconnect' | 'message' | BrocaMessageType

export type BrocaHandler = (payload?: any) => void

export class BrocaSocketClient {
  // placeholder to keep TS happy
  private handlers: Map<BrocaEventName, Set<BrocaHandler>> = new Map()

  constructor(public options: BrocaConnectionOptions) {}

  on(event: BrocaEventName, handler: BrocaHandler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set())
    this.handlers.get(event)!.add(handler)
    return () => this.handlers.get(event)!.delete(handler)
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async connect(): Promise<void> {
    // TODO: implement with socket.io-client
    throw new Error('socket.io-client dependency not installed yet')
  }

  async disconnect(): Promise<void> {
    // TODO
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async subscribe(subscription: string): Promise<void> {
    // TODO
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async sendUserMessage(params: {
    content: string
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    // TODO
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async sendCommand(params: {
    command: string
    arguments?: Record<string, any>
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    // TODO
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async sendPermissionResponse(params: {
    granted: boolean
    requestId?: string
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    // TODO
  }
}
