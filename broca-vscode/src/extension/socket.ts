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

  // 多路复用处理器（类似 Web 前端的 Map 模式）
  // Map 值用 NonNullable 包裹，因为 on() 和 setEventHandlers() 只存入非空 handler
  private _handlers: { [K in keyof SocketEventHandler]: Map<string, NonNullable<SocketEventHandler[K]>> } = {
    onConnect: new Map(),
    onDisconnect: new Map(),
    onMessage: new Map(),
    onError: new Map(),
  }

  // 订阅引用计数
  private _subscriptionRefCounts = new Map<string, number>()

  constructor(configManager: ConfigManager, getToken: () => string | null) {
    this.configManager = configManager
    this.getToken = getToken
    this.clientId = `vscode_${Math.random().toString(16).slice(2)}`
  }

  /**
   * Callback invoked when an authentication error (401-like) occurs during connection.
   * Typically wired to AuthManager.handleAuthError() for automatic logout + login prompt.
   */
  onAuthError: (() => void) | null = null

  /** 获取事件对应的 Map（非空，因为初始化时已定义所有 key） */
  private _getHandlerMap<K extends keyof SocketEventHandler>(event: K): Map<string, NonNullable<SocketEventHandler[K]>> {
    return this._handlers[event]!
  }

  /**
   * 注册事件处理器
   * @param event 事件名
   * @param id 处理器唯一标识（用于取消注册）
   * @param handler 处理函数
   * @returns 取消注册函数
   */
  on<K extends keyof SocketEventHandler>(
    event: K,
    id: string,
    handler: NonNullable<SocketEventHandler[K]>
  ): () => void {
    this._getHandlerMap(event).set(id, handler)
    return () => { this._getHandlerMap(event).delete(id) }
  }

  /** 取消注册事件处理器 */
  off<K extends keyof SocketEventHandler>(event: K, id: string): void {
    this._getHandlerMap(event).delete(id)
  }

  /**
   * 批量注册事件处理器（兼容旧 API）
   * 内部仍使用多路复用 Map，以 "default" 为 id
   */
  setEventHandlers(handlers: SocketEventHandler) {
    type HandlerKey = keyof SocketEventHandler
    for (const key of Object.keys(handlers) as HandlerKey[]) {
      const handler = handlers[key]
      if (handler) {
        this._getHandlerMap(key as HandlerKey).set('default', handler as any)
      }
    }
  }

  async connect(): Promise<void> {
    if (this.socket?.connected) return

    const token = this.getToken()

    this.socket = io(this.configManager.wsUrl, {
      transports: ['websocket', 'polling'],
      auth: {
        client_type: 'vscode',
        client_id: this.clientId,
        token: token,
      },
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    })

    this.socket.on('connect', () => {
      console.log('Socket connected')
      this._getHandlerMap('onConnect').forEach(h => h())

      // 重连后重新订阅所有此前已订阅的频道。
      // 服务端在 disconnect 时会清除客户端的订阅状态，
      // 因此 Socket.IO 自动重连后必须显式重新订阅。
      for (const [channel] of this._subscriptionRefCounts) {
        this._doSubscribe(channel).catch((err) => {
          console.error(`重连后重新订阅失败 ${channel}:`, err)
        })
      }
    })

    this.socket.on('disconnect', (reason) => {
      console.log('Socket disconnected:', reason)
      this._getHandlerMap('onDisconnect').forEach(h => h())
    })

    this.socket.on('connect_error', (error) => {
      console.error('Socket connection error:', error)

      // Detect authentication errors (401 or auth-related messages)
      const isAuthError =
        (error as any)?.data?.status === 401 ||
        /401|unauthorized|authentication|jwt|token/i.test(error.message || '')

      if (isAuthError) {
        console.error('[Socket] Authentication error detected, triggering auto-logout')
        this.onAuthError?.()
      }

      this._getHandlerMap('onError').forEach(h => h(error))
    })

    this.socket.on('message', (data: any) => {
      try {
        const message = this.parseMessage(data)
        this._getHandlerMap('onMessage').forEach(h => h(message))
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

  /**
   * 订阅频道（带引用计数）
   * @returns 取消订阅函数（引用计数归零时才真正取消）
   */
  async subscribe(sessionId: string): Promise<() => Promise<void>> {
    if (!this.socket?.connected) {
      throw new Error('Not connected')
    }

    const channels = [sessionId, `crew:${sessionId}`]

    for (const channel of channels) {
      const count = this._subscriptionRefCounts.get(channel) || 0
      if (count === 0) {
        await this._doSubscribe(channel)
      }
      this._subscriptionRefCounts.set(channel, count + 1)
    }

    return async () => {
      for (const channel of channels) {
        const count = this._subscriptionRefCounts.get(channel) || 0
        if (count <= 1) {
          this._subscriptionRefCounts.delete(channel)
          await this._doUnsubscribe(channel).catch(() => {})
        } else {
          this._subscriptionRefCounts.set(channel, count - 1)
        }
      }
    }
  }

  private _doSubscribe(subscription: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket!.emit('subscribe', { subscription }, (response: any) => {
        if (response?.error) reject(new Error(response.error))
        else resolve()
      })
    })
  }

  private _doUnsubscribe(subscription: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket!.emit('unsubscribe', { subscription }, (response: any) => {
        if (response?.error) reject(new Error(response.error))
        else resolve()
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
    if (!this.socket?.connected) {
      console.log('[Socket] sendUserMessage FAILED: not connected')
      throw new Error('Not connected')
    }

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

    console.log('[Socket] Emitting message:', { messageId: params.messageId, receiverId: params.receiverId, subscription: params.subscription })

    return new Promise((resolve, reject) => {
      this.socket!.emit('message', message, (response: any) => {
        console.log('[Socket] Emit response:', response)
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
    session_action?: string
    requestId?: string
    receiverId?: string
    subscription?: string
  }): Promise<void> {
    if (!this.socket?.connected) throw new Error('Not connected')

    const data: Record<string, unknown> = {
      granted: params.granted,
      request_id: params.requestId,
    }
    if (params.session_action) {
      data.session_action = params.session_action
    }

    const message: Message = {
      message_id: `perm_${Date.now()}`,
      message_type: 'permission_response',
      timestamp: new Date().toISOString(),
      role: 'system',
      sender_id: this.clientId,
      receiver_id: params.receiverId,
      subscription: params.subscription,
      data,
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
    this._subscriptionRefCounts.clear()
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
