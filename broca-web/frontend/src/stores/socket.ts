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

  const statusText = computed(() => {
    if (connecting.value) return 'connecting'
    return connected.value ? 'connected' : 'disconnected'
  })

  const onConnect = ref<(() => void) | null>(null)
  const onDisconnect = ref<(() => void) | null>(null)
  const onMessage = ref<((message: Message) => void) | null>(null)
  const onTurnStart = ref<((message: Message) => void) | null>(null)
  const onTurnEnd = ref<((message: Message) => void) | null>(null)
  const onAgentResponse = ref<((message: Message) => void) | null>(null)
  const onToolCall = ref<((message: Message) => void) | null>(null)
  const onPermissionRequest = ref<((message: Message) => void) | null>(null)
  const onAgentQuery = ref<((message: Message) => void) | null>(null)

  const connect = async () => {
    if (connected.value || connecting.value) return
    connecting.value = true
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
        onMessage.value?.(m)
      })
      client.on('turn_start', (m: Message) => {
        onTurnStart.value?.(m)
      })
      client.on('turn_end', (m: Message) => {
        onTurnEnd.value?.(m)
      })
      client.on('agent_response', (m: Message) => {
        onAgentResponse.value?.(m)
      })
      client.on('tool_call', (m: Message) => {
        onToolCall.value?.(m)
      })
      client.on('permission_request', (m: Message) => {
        onPermissionRequest.value?.(m)
      })
      client.on('agent_query', (m: Message) => {
        onAgentQuery.value?.(m)
      })

      await client.connect()
    } catch (e: any) {
      connecting.value = false
      connected.value = false
      ElMessage.error(e?.message || '连接失败')
      throw e
    }
  }

  const disconnect = () => {
    if (client) {
      client.disconnect()
      client = null
    }
    connected.value = false
    connecting.value = false
  }

  const subscribe = async (sessionId: string) => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }
    if (!sessionId.trim()) {
      ElMessage.warning('请输入session_id')
      return
    }
    try {
      await client.subscribe(sessionId.trim())
    } catch (e: any) {
      ElMessage.error(e?.message || '订阅失败')
      throw e
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
    requestId?: string
    receiverId?: string
    subscription?: string
  }) => {
    if (!client) return
    try {
      await client.sendPermissionResponse({
        granted: params.granted,
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
