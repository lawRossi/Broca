// Lightweight Socket.IO client wrapper for Broca protocol.
//
// Implementation mirrors Broca/comm/socketio_client.py:
// - listen on 'message'
// - parse Message
// - dispatch by message_type (agent_response/turn_start/permission_request...)

import { io, type Socket } from 'socket.io-client'
import type { Message, MessageType, MessageRole } from './types'

// 导出共享的类型
export type { Message, MessageType, MessageRole }


export interface BrocaConnectionOptions {
  serverUrl: string
  clientType: string
  clientId: string
  userId?: string
}

export type BrocaEventName = 'connect' | 'disconnect' | 'message' | MessageType

export type BrocaHandler = (payload?: any) => void

export class BrocaSocketClient {
  private socket: Socket | null = null
  private handlers: Map<BrocaEventName, Set<BrocaHandler>> = new Map()
  private isConnected = false

  private options: BrocaConnectionOptions
  
  constructor(options: BrocaConnectionOptions) {
    this.options = options
  }

  on(event: BrocaEventName, handler: BrocaHandler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set())
    const eventHandlers = this.handlers.get(event)
    if (eventHandlers) {
      eventHandlers.add(handler)
    }
    return () => {
      const eventHandlers = this.handlers.get(event)
      if (eventHandlers) {
        eventHandlers.delete(handler)
      }
    }
  }

  private emit(event: BrocaEventName, payload?: any) {
    const handlers = this.handlers.get(event)
    if (handlers) {
      handlers.forEach(handler => handler(payload))
    }
  }

  async connect(): Promise<void> {
    if (this.socket) {
      await this.disconnect()
    }

    this.socket = io(this.options.serverUrl, {
      transports: ['websocket', 'polling'],
      auth: {
        client_type: this.options.clientType,
        client_id: this.options.clientId,
        user_id: this.options.userId,
      },
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      randomizationFactor: 0.5,
      autoConnect: false,
    })

    // Setup socket.io event handlers
    this.socket.on('connect', () => {
      console.log('Socket.io connected successfully')
      this.isConnected = true
      this.emit('connect')
    })

    this.socket.on('disconnect', (reason: string) => {
      console.log(`Socket.io disconnected: ${reason}`)
      this.isConnected = false
      this.emit('disconnect', reason)
    })

    this.socket.on('connect_error', (error: any) => {
      console.error('Socket.io connection error:', error)
      this.emit('error', error)
    })

    this.socket.on('message', (data: any) => {
      try {
        const message = this.parseMessage(data)
        this.emit('message', message)
        
        // Dispatch by message_type (mirroring broca.comm.socketio_client.py)
        if (message.message_type) {
          this.emit(message.message_type, message)
        }
      } catch (error) {
        console.error('Failed to parse message:', error, data)
        this.emit('error', { error, raw: data })
      }
    })

    // Manually connect
    this.socket.connect()

    return new Promise((resolve, reject) => {
      if (this.socket!.connected) {
        console.log('Socket already connected')
        resolve()
        return
      }

      const timeout = setTimeout(() => {
        console.log('Connection timeout')
        reject(new Error('Connection timeout after 20 seconds'))
      }, 20000)

      this.socket!.once('connect', () => {
        console.log('Connection established successfully')
        clearTimeout(timeout)
        resolve()
      })

      this.socket!.once('connect_error', (error: any) => {
        console.error('Connection failed:', error)
        clearTimeout(timeout)
        reject(new Error(`Connection failed: ${error.message || error}`))
      })
    })
  }

  async disconnect(): Promise<void> {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
      this.isConnected = false
    }
  }

  async subscribe(subscription: string): Promise<void> {
    if (!this.socket || !this.isConnected) {
      throw new Error('Not connected')
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('subscribe', { subscription }, (response: any) => {
        if (response?.error) {
          reject(new Error(response.error))
        } else {
          resolve()
        }
      })
    })
  }

  async sendUserMessage(params: {
    content: string
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket || !this.isConnected) {
      throw new Error('Not connected')
    }

    const message: Message = {
      message_id: this.generateMessageId(),
      message_type: 'user_message',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: this.options.clientId,
      receiver_id: params.receiverId,
      room: params.room,
      subscription: params.subscription,
      data: {
        content: params.content,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) {
          reject(new Error(response.error))
        } else {
          resolve()
        }
      })
    })
  }

  async sendCommand(params: {
    command: string
    arguments?: Record<string, any>
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket || !this.isConnected) {
      throw new Error('Not connected')
    }

    const message: Message = {
      message_id: this.generateMessageId(),
      message_type: 'command',
      timestamp: new Date().toISOString(),
      role: 'system',
      sender_id: this.options.clientId,
      receiver_id: params.receiverId,
      room: params.room,
      subscription: params.subscription,
      data: {
        command: params.command,
        arguments: params.arguments,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) {
          reject(new Error(response.error))
        } else {
          resolve()
        }
      })
    })
  }

  async sendPermissionResponse(params: {
    granted: boolean
    requestId?: string
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket || !this.isConnected) {
      throw new Error('Not connected')
    }

    const message: Message = {
      message_id: this.generateMessageId(),
      message_type: 'permission_response',
      timestamp: new Date().toISOString(),
      role: 'system',
      sender_id: this.options.clientId,
      receiver_id: params.receiverId,
      room: params.room,
      subscription: params.subscription,
      data: {
        granted: params.granted,
        request_id: params.requestId,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) {
          reject(new Error(response.error))
        } else {
          resolve()
        }
      })
    })
  }

  async sendUserAnswer(params: {
    answer: string
    requestId?: string
    receiverId?: string
    room?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket || !this.isConnected) {
      throw new Error('Not connected')
    }

    const message: Message = {
      message_id: this.generateMessageId(),
      message_type: 'user_answer',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: this.options.clientId,
      receiver_id: params.receiverId,
      room: params.room,
      subscription: params.subscription,
      data: {
        answer: params.answer,
        request_id: params.requestId,
      },
    }

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        if (response?.error) {
          reject(new Error(response.error))
        } else {
          resolve()
        }
      })
    })
  }

  private parseMessage(data: any): Message {
    // Ensure data has required fields
    if (!data || typeof data !== 'object') {
      throw new Error('Invalid message format')
    }

    return {
      message_id: data.message_id || `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`,
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

  private generateMessageId(): string {
    return `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`
  }

  get connected(): boolean {
    return this.isConnected
  }
}
