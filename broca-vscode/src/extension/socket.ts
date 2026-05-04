import { io, type Socket } from 'socket.io-client'
import type { ConfigManager } from './config'
import type { Message } from './types'

export type SocketEventHandler = {
  onConnect?: () => void
  onDisconnect?: () => void
  onMessage?: (message: Message) => void
  onError?: (error: any) => void
}

export class SocketClient {
  private socket: Socket | null = null
  private configManager: ConfigManager
  private getToken: () => string | null
  private clientId: string
  private eventHandlers: SocketEventHandler = {}

  constructor(configManager: ConfigManager, getToken: () => string | null) {
    this.configManager = configManager
    this.getToken = getToken
    this.clientId = `vscode_${Math.random().toString(16).slice(2)}`
  }

  setEventHandlers(handlers: SocketEventHandler) {
    this.eventHandlers = handlers
  }

  async connect(): Promise<void> {
    if (this.socket?.connected) return

    const token = this.getToken()

    this.socket = io(this.configManager.wsUrl, {
      transports: ['websocket', 'polling'],
      auth: {
        client_type: 'vscode',
        client_id: this.clientId,
        user_id: token ? undefined : undefined,
        token: token,
      },
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    })

    this.socket.on('connect', () => {
      console.log('Socket connected')
      this.eventHandlers.onConnect?.()
    })

    this.socket.on('disconnect', (reason) => {
      console.log('Socket disconnected:', reason)
      this.eventHandlers.onDisconnect?.()
    })

    this.socket.on('connect_error', (error) => {
      console.error('Socket connection error:', error)
      this.eventHandlers.onError?.(error)
    })

    this.socket.on('message', (data: any) => {
      try {
        const message = this.parseMessage(data)
        this.eventHandlers.onMessage?.(message)
      } catch (error) {
        console.error('Failed to parse message:', error)
      }
    })

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Connection timeout')), 20000)

      this.socket!.once('connect', () => {
        clearTimeout(timeout)
        resolve()
      })

      this.socket!.once('connect_error', (error) => {
        clearTimeout(timeout)
        reject(error)
      })
    })
  }

  async subscribe(sessionId: string): Promise<void> {
    if (!this.socket?.connected) {
      throw new Error('Not connected')
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('subscribe', { subscription: sessionId }, (response: any) => {
        if (response?.error) {
          reject(new Error(response.error))
        } else {
          resolve()
        }
      })
    })
  }

  async sendUserMessage(params: {
    messageId: string
    content: string
    receiverId?: string
    subscription?: string
    files?: Array<{
      name: string
      url: string
      path: string
      size: number
      type: string
      upload_time: string
    }>
  }): Promise<void> {
    if (!this.socket?.connected) throw new Error('Not connected')

    const message: Message = {
      message_id: params.messageId,
      message_type: 'user_message',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: this.clientId,
      receiver_id: params.receiverId,
      subscription: params.subscription,
      data: {
        content: params.content,
        ...(params.files && { files: params.files }),
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) reject(new Error(response.error))
        else resolve()
      })
    })
  }

  async sendCommand(params: {
    command: string
    arguments?: Record<string, any>
    receiverId?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket?.connected) throw new Error('Not connected')

    const message: Message = {
      message_id: `cmd_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      message_type: 'command',
      timestamp: new Date().toISOString(),
      role: 'system',
      sender_id: this.clientId,
      receiver_id: params.receiverId,
      subscription: params.subscription,
      data: {
        command: params.command,
        arguments: params.arguments,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) reject(new Error(response.error))
        else resolve()
      })
    })
  }

  async sendPermissionResponse(params: {
    granted: boolean
    requestId?: string
    receiverId?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket?.connected) throw new Error('Not connected')

    const message: Message = {
      message_id: `perm_${Date.now()}`,
      message_type: 'permission_response',
      timestamp: new Date().toISOString(),
      role: 'system',
      sender_id: this.clientId,
      receiver_id: params.receiverId,
      subscription: params.subscription,
      data: {
        granted: params.granted,
        request_id: params.requestId,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) reject(new Error(response.error))
        else resolve()
      })
    })
  }

  async sendUserAnswer(params: {
    answer: string
    requestId?: string
    receiverId?: string
  }): Promise<void> {
    if (!this.socket?.connected) throw new Error('Not connected')

    const message: Message = {
      message_id: `ans_${Date.now()}`,
      message_type: 'user_answer',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: this.clientId,
      receiver_id: params.receiverId,
      data: {
        answer: params.answer,
        request_id: params.requestId,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) reject(new Error(response.error))
        else resolve()
      })
    })
  }

  disconnect(): void {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
    }
  }

  get connected(): boolean {
    return this.socket?.connected || false
  }

  private parseMessage(data: any): Message {
    return {
      message_id: data.message_id || `msg_${Date.now()}`,
      message_type: data.message_type || 'unknown',
      timestamp: data.timestamp || new Date().toISOString(),
      role: data.role || 'assistant',
      sender_id: data.sender_id,
      receiver_id: data.receiver_id,
      room: data.room,
      subscription: data.subscription,
      session_id: data.session_id,
      turn_id: data.turn_id,
      agent_id: data.agent_id,
      sequence_number: data.sequence_number,
      data: data.data || {},
    }
  }
}
