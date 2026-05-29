import { defineStore } from 'pinia'
import { ref, computed, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores'
import { BrocaSocketClient, type Message } from '@/api/brocaSocket'

const serverUrl = import.meta.env.VITE_BROCA_SOCKET_SERVER_URL

export const useSocketStore = defineStore('socket', () => {
  const userStore = useUserStore()

  const connected = ref(false)
  const connecting = ref(false)

  const socketConfig = reactive({
    serverUrl: serverUrl,
    clientType: 'browser',
    clientId: `browser_${Math.random().toString(16).slice(2)}`,
    userId: computed(() => userStore.userId || undefined),
  })

  let client: BrocaSocketClient | null = null
  /** Track the in-progress connection promise so callers can await it */
  let _connectPromise: Promise<void> | null = null

  const statusText = computed(() => {
    if (connecting.value) return 'connecting'
    return connected.value ? 'connected' : 'disconnected'
  })

  const onConnect = ref<(() => void) | null>(null)
  const onDisconnect = ref<((() => void) | null)>(null)

  // 使用 Map 支持多组件同时注册处理器，避免单例覆盖问题
  const _messageHandlers = new Map<string, (message: Message) => void>()
  const _crewEventHandlers = new Map<string, (event: string, data: any) => void>()
  const _turnStartHandlers = new Map<string, (message: Message) => void>()
  const _turnEndHandlers = new Map<string, (message: Message) => void>()
  const _agentResponseHandlers = new Map<string, (message: Message) => void>()
  const _toolCallHandlers = new Map<string, (message: Message) => void>()
  const _permissionRequestHandlers = new Map<string, (message: Message) => void>()
  const _agentQueryHandlers = new Map<string, (message: Message) => void>()

  /** 注册消息处理器，返回注销函数 */
  const onMessage = (id: string, handler: (message: Message) => void): (() => void) => {
    _messageHandlers.set(id, handler)
    return () => { _messageHandlers.delete(id) }
  }
  const onCrewEvent = (id: string, handler: (event: string, data: any) => void): (() => void) => {
    _crewEventHandlers.set(id, handler)
    return () => { _crewEventHandlers.delete(id) }
  }
  const onTurnStart = (id: string, handler: (message: Message) => void): (() => void) => {
    _turnStartHandlers.set(id, handler)
    return () => { _turnStartHandlers.delete(id) }
  }
  const onTurnEnd = (id: string, handler: (message: Message) => void): (() => void) => {
    _turnEndHandlers.set(id, handler)
    return () => { _turnEndHandlers.delete(id) }
  }
  const onAgentResponse = (id: string, handler: (message: Message) => void): (() => void) => {
    _agentResponseHandlers.set(id, handler)
    return () => { _agentResponseHandlers.delete(id) }
  }
  const onToolCall = (id: string, handler: (message: Message) => void): (() => void) => {
    _toolCallHandlers.set(id, handler)
    return () => { _toolCallHandlers.delete(id) }
  }
  const onPermissionRequest = (id: string, handler: (message: Message) => void): (() => void) => {
    _permissionRequestHandlers.set(id, handler)
    return () => { _permissionRequestHandlers.delete(id) }
  }
  const onAgentQuery = (id: string, handler: (message: Message) => void): (() => void) => {
    _agentQueryHandlers.set(id, handler)
    return () => { _agentQueryHandlers.delete(id) }
  }

  const connect = async () => {
    // Already connected — nothing to do
    if (connected.value) return
    // Connection already in progress — wait for it to complete
    if (connecting.value && _connectPromise) {
      return _connectPromise
    }
    connecting.value = true
    _connectPromise = (async () => {
      try {
      client = new BrocaSocketClient({
        serverUrl: socketConfig.serverUrl,
        clientType: socketConfig.clientType,
        clientId: socketConfig.clientId,
        userId: socketConfig.userId,
      })

      client.on('connect', () => {
        connected.value = true
        connecting.value = false
        onConnect.value?.()
      })
      client.on('disconnect', () => {
        connected.value = false
        connecting.value = false
        onDisconnect.value?.()
      })
      client.on('message', (m: Message) => {
        // 广播给所有注册的消息处理器
        _messageHandlers.forEach(h => h(m))
        // 如果是编排事件，路由到所有编排事件处理器
        if (m.message_type === 'system_message' && m.data?.crew_event) {
          _crewEventHandlers.forEach(h => h(m.data.crew_event, m.data.payload))
        }
      })
      client.on('turn_start', (m: Message) => {
        _turnStartHandlers.forEach(h => h(m))
      })
      client.on('turn_end', (m: Message) => {
        _turnEndHandlers.forEach(h => h(m))
      })
      client.on('agent_response', (m: Message) => {
        _agentResponseHandlers.forEach(h => h(m))
      })
      client.on('tool_call', (m: Message) => {
        _toolCallHandlers.forEach(h => h(m))
      })
      client.on('permission_request', (m: Message) => {
        _permissionRequestHandlers.forEach(h => h(m))
      })
      client.on('agent_query', (m: Message) => {
        _agentQueryHandlers.forEach(h => h(m))
      })

      await client.connect()
    } catch (e: any) {
      connecting.value = false
      connected.value = false
      ElMessage.error(e?.message || '连接失败')
      throw e
    } finally {
      _connectPromise = null
      // 连接完成（无论成功或失败）后清除 promise
    }
    })()
    return _connectPromise
  }

  const disconnect = () => {
    _connectPromise = null
    if (client) {
      client.disconnect()
      client = null
    }
    connected.value = false
    connecting.value = false
  }

  /** 订阅引用计数，安全支持多组件同时订阅同一频道 */
  const _subscriptionRefCounts = new Map<string, number>()

  /**
   * 订阅频道（带引用计数）
   * 
   * 多个组件可以安全地订阅同一频道，各自独立 unsubscribe。
   * 只有当引用计数归零时才真正向服务端发送取消订阅。
   * 
   * @param sessionId 会话 ID
   * @param subscribeToCrew 是否同时订阅编排事件频道
   * @returns 取消订阅函数，调用后引用计数减一
   */
  const subscribe = async (sessionId: string, subscribeToCrew: boolean = true): Promise<() => Promise<void>> => {
    if (!client) {
      ElMessage.warning('请先连接')
      return async () => {}
    }
    if (!sessionId.trim()) {
      ElMessage.warning('请输入session_id')
      return async () => {}
    }

    const channels: string[] = [sessionId.trim()]
    if (subscribeToCrew) {
      channels.push(`crew:${sessionId.trim()}`)
    }

    // 对每个频道递增引用计数，首次订阅才实际请求服务端
    for (const channel of channels) {
      const count = _subscriptionRefCounts.get(channel) || 0
      if (count === 0) {
        try {
          await client.subscribe(channel)
        } catch (e: any) {
          ElMessage.error(e?.message || `订阅 ${channel} 失败`)
          throw e
        }
      }
      _subscriptionRefCounts.set(channel, count + 1)
    }

    onConnect.value?.()

    // 返回取消订阅函数：引用计数减一，归零时真正取消
    return async () => {
      for (const channel of channels) {
        const count = _subscriptionRefCounts.get(channel) || 0
        if (count <= 1) {
          _subscriptionRefCounts.delete(channel)
          try {
            if (client) await client.unsubscribe(channel)
          } catch {
            // 取消订阅失败不影响功能
          }
        } else {
          _subscriptionRefCounts.set(channel, count - 1)
        }
      }
    }
  }

  const sendUserMessage = async (params: {
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
  }) => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }
    const text = params.content.trim()
    if (!text && (!params.files || params.files.length === 0)) return

    try {
      await client.sendUserMessage({
        messageId: params.messageId,
        content: text,
        receiverId: params.receiverId,
        subscription: params.subscription,
        files: params.files,
      })
    } catch (e: any) {
      ElMessage.error(e?.message || '发送失败')
    }
  }

  const sendAbort = async (params: { subscription?: string; receiverId?: string }) => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }

    try {
      await client.sendCommand({
        command: 'abort',
        arguments: {},
        subscription: params.subscription,
        receiverId: params.receiverId,
      })
      ElMessage.success('Abort 命令已发送')
    } catch (e: any) {
      ElMessage.error(e?.message || '发送 abort 失败')
    }
  }

  const respondPermission = async (params: {
    granted: boolean
    session_action?: string
    requestId?: string
    receiverId?: string
    subscription?: string
  }) => {
    if (!client) return
    try {
      await client.sendPermissionResponse({
        granted: params.granted,
        session_action: params.session_action,
        requestId: params.requestId,
        receiverId: params.receiverId,
        subscription: params.subscription,
      })
    } catch (e: any) {
      ElMessage.error(e?.message || '权限响应失败')
    }
  }

  const sendUserAnswer = async (params: { answer: string; requestId?: string; receiverId?: string }) => {
    if (!client) return
    console.log(params)
    try {
      await client.sendUserAnswer({
        answer: params.answer,
        requestId: params.requestId,
        receiverId: params.receiverId,
      })
    } catch (e: any) {
      ElMessage.error(e?.message || '发送回答失败')
    }
  }

  const sendUndo = async (params: {
    targetMessageId?: string
    level?: 'turn' | 'step'
    subscription?: string
    receiverId?: string
  }) => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }
    try {
      await client.sendCommand({
        command: 'undo',
        arguments: {
          target_message_id: params.targetMessageId,
          level: params.level || 'step'
        },
        subscription: params.subscription,
        receiverId: params.receiverId,
      })
      ElMessage.success('撤销命令已发送')
    } catch (e: any) {
      ElMessage.error(e?.message || '发送撤销命令失败')
    }
  }

  const sendRedo = async (params: {
    receiverId?: string
  }) => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }
    try {
      await client.sendCommand({
        command: 'redo',
        arguments: {},
        receiverId: params.receiverId,
      })
      ElMessage.success('重做命令已发送')
    } catch (e: any) {
      ElMessage.error(e?.message || '发送重做命令失败')
    }
  }

  const cleanup = () => {
    disconnect()
    socketConfig.clientId = `browser_${Math.random().toString(16).slice(2)}`
  }

  return {
    connected,
    connecting,
    socketConfig,
    statusText,
    onConnect,
    onDisconnect,
    onMessage,
    onCrewEvent,
    onTurnStart,
    onTurnEnd,
    onAgentResponse,
    onToolCall,
    onPermissionRequest,
    onAgentQuery,
    connect,
    disconnect,
    subscribe,
    sendUserMessage,
    sendAbort,
    respondPermission,
    sendUserAnswer,
    sendUndo,
    sendRedo,
    cleanup,
  }
})
