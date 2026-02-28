import { defineStore } from 'pinia'
import { ref, computed, reactive, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores'
import { BrocaSocketClient, type BrocaMessage } from '@/api/brocaSocket'
import { sessionApi } from '@/api/session'

export const DisplayType = {
  USER: 'user',
  ASSISTANT: 'assistant',
  SYSTEM: 'system',
  ERROR: 'error',
  THINKING: 'thinking',
  TOOL_CALL: 'tool_call',
} as const

export type DisplayType = typeof DisplayType[keyof typeof DisplayType]

export type UiMessage = {
  id: string
  ts: string
  type: string
  displayType: DisplayType
  sender?: string
  receiver?: string
  subscription?: string
  content?: string
  raw: BrocaMessage
  showParameters?: boolean
}

export type AgentStatus = 'idle' | 'running' | 'connecting' | 'disconnected'

export const useChatStore = defineStore('chat', () => {
  const route = useRoute()
  const userStore = useUserStore()

  const connected = ref(false)
  const connecting = ref(false)
  const sessionId = ref<string>('')
  const agentId = ref('main_agent')
  const agentName = ref('Assistant')
  const agentStatus = ref<AgentStatus>('disconnected')
  const input = ref('')
  const loading = ref(false)
  const loadingMore = ref(false)
  const hasMoreHistory = ref(true)
  const historySkip = ref(0)
  const historyTotal = ref(0)
  const messagesContainer = ref<HTMLElement>()

  const showLeftSidebar = ref(false)
  const showRightSidebar = ref(false)
  const isMobile = ref(false)

  const messageFilters = reactive({
    showUser: true,
    showAssistant: true,
    showSystem: true,
    showError: true,
  })

  const urlSessionId = computed(() => {
    return route.params.session_id as string || route.query.session_id as string || ''
  })

  const permissionDialog = reactive({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    message: '',
  })

  const socketConfig = reactive({
    serverUrl: 'http://81.71.49.200:6868',
    clientType: 'browser',
    clientId: `browser_${Math.random().toString(16).slice(2)}`,
    userId: computed(() => userStore.userId || undefined),
  })

  const uiMessages = ref<UiMessage[]>([])

  const filteredMessages = computed(() => {
    return uiMessages.value.filter(msg => {
      switch (msg.displayType) {
        case DisplayType.USER:
          return messageFilters.showUser
        case DisplayType.ASSISTANT:
          return messageFilters.showAssistant
        case DisplayType.SYSTEM:
          return messageFilters.showSystem
        case DisplayType.ERROR:
          return messageFilters.showError
        case DisplayType.THINKING:
          return messageFilters.showAssistant
        case DisplayType.TOOL_CALL:
          return messageFilters.showAssistant
        default:
          return true
      }
    })
  })

  const statusText = computed(() => {
    if (connecting.value) return 'connecting'
    return connected.value ? 'connected' : 'disconnected'
  })

  const agentStatusText = computed(() => {
    switch (agentStatus.value) {
      case 'idle':
        return 'Agent Idle'
      case 'running':
        return 'Agent Running...'
      case 'connecting':
        return 'Agent Connecting...'
      case 'disconnected':
        return 'Agent Disconnected'
      default:
        return 'Unknown'
    }
  })

  let client: BrocaSocketClient | null = null

  const checkMobile = () => {
    isMobile.value = window.innerWidth < 1024
    if (!isMobile.value) {
      showLeftSidebar.value = true
      showRightSidebar.value = true
    }
  }

  const toggleLeftSidebar = () => {
    showLeftSidebar.value = !showLeftSidebar.value
    if (showLeftSidebar.value) showRightSidebar.value = false
  }

  const toggleRightSidebar = () => {
    showRightSidebar.value = !showRightSidebar.value
    if (showRightSidebar.value) showLeftSidebar.value = false
  }

  const scrollToBottom = () => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  }

  const toggleToolParameters = (messageId: string) => {
    const message = uiMessages.value.find(m => m.id === messageId)
    if (message && message.displayType === DisplayType.TOOL_CALL) {
      message.showParameters = !message.showParameters
    }
  }

  const parseMessageContent = (content: string | undefined): string => {
    if (!content) return ''
    try {
      const parsed = JSON.parse(content)
      if (parsed.tool_calls && Array.isArray(parsed.tool_calls) && parsed.tool_calls.length > 0) {
        return JSON.stringify(parsed, null, 2)
      }
      return parsed.content || JSON.stringify(parsed, null, 2)
    } catch {
      return content
    }
  }

  const normalizeToBrocaMessage = (msg: any): BrocaMessage => {
    if (msg.sender_id !== undefined) {
      return msg as BrocaMessage
    }
    let message_type = msg.message_type
    if (msg.message_type === 'text') {
      if (msg.role == 'user') {
        message_type = 'user_message'
      } else if (msg.role == 'assistant') {
        message_type = 'agent_response'
      }
    }
  
    return {
      message_id: msg.message_id,
      message_type: message_type,
      timestamp: msg.timestamp,
      sender_id: msg.role === 'user' ? 'user' : msg.agent_id,
      receiver_id: msg.role === 'user' ? msg.agent_id : 'user',
      subscription: msg.session_id,
      data: msg.data || { content: msg.content },
    }
  }

  const convertToUiMessages = (msg: any, sessionId?: string): UiMessage[] => {
    const normalized = normalizeToBrocaMessage(msg)

    if (normalized.message_type === 'turn_start' || normalized.message_type === 'turn_end') {
      return []
    }

    if (normalized.message_type === 'command') {
      return []
    }

    if (normalized.message_type === 'permission_request') {
      return []
    }

    const contentStr = normalized.data?.content ?? normalized.data?.message ?? ''
    if (typeof contentStr === 'string' && (contentStr.toLowerCase().includes('connected to') || contentStr.toLowerCase().includes('subscribed to'))) {
      return []
    }

    if ((normalized.message_type === 'agent_response' || normalized.sender_id === 'assistant') && normalized.data?.content) {
      try {
        const contentObj = JSON.parse(normalized.data.content)

        if (contentObj.tool_calls && Array.isArray(contentObj.tool_calls) && contentObj.tool_calls.length > 0) {
          const results: UiMessage[] = []

          if (contentObj.content || contentObj.reasoning_content) {
            let assistantContent = ''
            if (contentObj.content) {
              assistantContent = contentObj.content
            }
            if (contentObj.reasoning_content) {
              if (assistantContent) {
                assistantContent += '\n\n推理过程:\n' + contentObj.reasoning_content
              } else {
                assistantContent = '推理过程:\n' + contentObj.reasoning_content
              }
            }

            results.push({
              id: `${normalized.message_id}_content`,
              ts: normalized.timestamp,
              type: normalized.message_type,
              displayType: DisplayType.ASSISTANT,
              sender: normalized.sender_id,
              receiver: normalized.receiver_id,
              subscription: normalized.subscription || sessionId,
              content: assistantContent,
              raw: normalized,
              showParameters: false           
            })
          }

          contentObj.tool_calls.forEach((toolCall: any, index: number) => {
            let toolName = 'unknown_tool'
            let argumentsData = {}

            if (toolCall.function) {
              toolName = toolCall.function.name || toolName
              try {
                argumentsData = JSON.parse(toolCall.function.arguments || '{}')
              } catch (e) {
                argumentsData = { raw_arguments: toolCall.function.arguments }
              }
            }

            results.push({
              id: `${normalized.message_id}_toolcall_${index}`,
              ts: normalized.timestamp,
              type: 'tool_call',
              displayType: DisplayType.TOOL_CALL,
              sender: normalized.sender_id,
              receiver: normalized.receiver_id,
              subscription: normalized.subscription || sessionId,
              content: toolName,
              raw: {
                message_id: `${normalized.message_id}_toolcall_${index}`,
                timestamp: normalized.timestamp,
                message_type: 'tool_call',
                sender_id: normalized.sender_id,
                receiver_id: normalized.receiver_id,
                subscription: normalized.subscription || sessionId,
                data: {
                  tool_name: toolName,
                  arguments: argumentsData
                }
              },
              showParameters: false
            })
          })

          return results
        }
      } catch (e) {
        console.debug('消息内容不是有效的JSON格式:', e)
      }
    }

    const processed = processMessageForDisplay(normalized, normalized.message_type)

    const uiMsg: UiMessage = {
      id: normalized.message_id,
      ts: normalized.timestamp,
      type: normalized.message_type,
      displayType: processed.displayType,
      sender: normalized.sender_id,
      receiver: normalized.receiver_id,
      subscription: normalized.subscription || sessionId,
      content: processed.content,
      raw: normalized,
      showParameters: false,
    }

    return [uiMsg]
  }

  const processMessageForDisplay = (messageData: any, messageType?: string): {
    content: string,
    displayType: DisplayType,
    data?: any
  } => {
    const msgType = messageType || messageData.message_type

    if (msgType === 'tool_call') {
      let toolName = 'unknown_tool'
      let argumentsData = {}

      if (messageData.data?.tool_name) {
        toolName = messageData.data.tool_name
        argumentsData = messageData.data.arguments || {}
      } else if (messageData.content) {
        try {
          const parsedContent = JSON.parse(messageData.content)
          toolName = parsedContent.tool_name || toolName
          argumentsData = parsedContent.arguments || argumentsData
        } catch (e) {
          console.error('解析tool_call消息失败:', e)
          toolName = messageData.content
        }
      }

      return {
        content: toolName,
        displayType: DisplayType.TOOL_CALL,
        data: {
          tool_name: toolName,
          arguments: argumentsData
        }
      }
    }

    let content = ''
    if (messageData.data?.content !== undefined) {
      content = messageData.data.content
    } else if (messageData.content) {
      content = messageData.content
    } else if (messageData.data?.message) {
      content = messageData.data.message
    } else if (messageData.error_message) {
      content = messageData.error_message
    }

    content = parseMessageContent(content)

    let displayType: DisplayType = DisplayType.ASSISTANT
    if (msgType === 'error' || messageData.error_message) {
      displayType = DisplayType.ERROR
    } else if (messageData.sender_id === 'system' || messageData.sender_id?.includes('system')) {
      displayType = DisplayType.SYSTEM
    } else if (messageData.sender_id === 'user' || messageData.sender_id?.includes('user') || (messageData as any).role === 'user') {
      displayType = DisplayType.USER
    } else if (msgType === 'tool_call') {
      displayType = DisplayType.TOOL_CALL
    }

    return {
      content,
      displayType
    }
  }

  const addUiMessage = (m: BrocaMessage, displayType?: DisplayType) => {
    if (displayType) {
      const uiMsg: UiMessage = {
        id: m.message_id,
        ts: m.timestamp,
        type: m.message_type,
        displayType,
        sender: m.sender_id,
        receiver: m.receiver_id,
        subscription: m.subscription,
        content: m.data?.content || '',
        raw: m,
        showParameters: false
      }
      uiMessages.value.push(uiMsg)
      return
    }

    const messages = convertToUiMessages(m)
    uiMessages.value.push(...messages)
  }

  const addSystemMessage = (content: string) => {
    const msg: UiMessage = {
      id: `system_${Date.now()}`,
      ts: new Date().toISOString(),
      type: 'system',
      displayType: DisplayType.SYSTEM,
      sender: 'system',
      content,
      raw: {} as BrocaMessage
    }
    uiMessages.value.push(msg)
  }

  const fetchAgentId = async (sessionId: string) => {
    try {
      loading.value = true
      const latestAgent = await sessionApi.getSessionLatestAgent(sessionId)
      agentId.value = latestAgent.agent_id
      agentName.value = latestAgent.agent_name || 'Assistant'
      agentStatus.value = 'idle'
    } catch (error: any) {
      console.error('获取Agent失败:', error)
      ElMessage.warning('获取Agent失败，使用默认Agent')
      agentName.value = 'Assistant'
      agentStatus.value = 'disconnected'
    } finally {
      loading.value = false
    }
  }

  const loadHistory = async (sessionId: string, isLoadMore: boolean = false) => {
    const limit = 50
    
    if (isLoadMore) {
      if (loadingMore.value || !hasMoreHistory.value) return
      loadingMore.value = true
    } else {
      loading.value = true
      historySkip.value = 0
      hasMoreHistory.value = true
      uiMessages.value = []
    }

    try {
      let skip: number
      if (isLoadMore) {
        skip = historySkip.value
      } else {
        const countResponse = await sessionApi.getSessionMessages(sessionId, 0, 1)
        historyTotal.value = countResponse.total || 0
        skip = 0
      }
      
      const response = await sessionApi.getSessionMessages(sessionId, skip, limit)
      
      if (response.messages) {
        const allMessages = response.messages
        
        const filteredMessages = allMessages.filter((msg: any) => 
          (msg.role === 'user' || msg.role === 'assistant') &&
          (parseMessageContent(msg.content) || msg.message_type === 'tool_call') &&
          msg.message_type !== 'command'
        )

        const historyMessages: UiMessage[] = []

        filteredMessages.forEach((msg: any) => {
          const converted = convertToUiMessages(msg, sessionId)
          historyMessages.push(...converted)
        })

        if (isLoadMore) {
          uiMessages.value = [...historyMessages, ...uiMessages.value]
        } else {
          uiMessages.value = historyMessages
        }
        historySkip.value = skip + limit

        hasMoreHistory.value = historySkip.value < historyTotal.value
      }
    } catch (error: any) {
      console.error('加载历史消息失败:', error)
    } finally {
      loading.value = false
      loadingMore.value = false
      if (!isLoadMore) {
        nextTick(() => scrollToBottom())
      }
    }
  }

  const doConnect = async () => {
    if (connected.value || connecting.value) return
    connecting.value = true
    agentStatus.value = 'connecting'
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
        agentStatus.value = 'idle'
        ElMessage.success('连接成功')
      })
      client.on('disconnect', () => {
        connected.value = false
        connecting.value = false
        agentStatus.value = 'disconnected'
        ElMessage.warning('连接断开')
      })
      client.on('message', (m: BrocaMessage) => {
        addUiMessage(m)
        scrollToBottom()
      })

      client.on('turn_start', () => {
        agentStatus.value = 'running'
      })
      client.on('turn_end', () => {
        agentStatus.value = 'idle'
      })
      client.on('agent_response', () => {
        agentStatus.value = 'running'
      })
      client.on('tool_call', () => {
        agentStatus.value = 'running'
      })

      client.on('permission_request', (m: BrocaMessage) => {
        permissionDialog.visible = true
        permissionDialog.requestId = m.data?.request_id
        permissionDialog.senderId = m.sender_id
        permissionDialog.message = m.data?.message || 'Permission required'
      })

      await client.connect()
    } catch (e: any) {
      connecting.value = false
      connected.value = false
      agentStatus.value = 'disconnected'
      ElMessage.error(e?.message || '连接失败')
      throw e
    }
  }

  const doSubscribe = async () => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }
    if (!sessionId.value.trim()) {
      ElMessage.warning('请输入session_id')
      return
    }
    try {
      await client.subscribe(sessionId.value.trim())
    } catch (e: any) {
      ElMessage.error(e?.message || '订阅失败')
      throw e
    }
  }

  const sendUserMessage = async () => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }
    const text = input.value.trim()
    if (!text) return

    input.value = ''

    addUiMessage({
      message_id: `user_${Date.now()}`,
      timestamp: new Date().toISOString(),
      message_type: 'user_message',
      sender_id: 'user',
      receiver_id: agentId.value,
      subscription: sessionId.value,
      data: { content: text }
    } as BrocaMessage, DisplayType.USER)

    try {
      await client.sendUserMessage({
        content: text,
        receiverId: agentId.value,
        subscription: sessionId.value,
      })
    } catch (e: any) {
      ElMessage.error(e?.message || '发送失败')
    }
  }

  const sendAbort = async () => {
    if (!client) {
      ElMessage.warning('请先连接')
      return
    }

    if (agentStatus.value !== 'running') {
      ElMessage.info('Agent 未在运行中，无需 abort')
      return
    }

    try {
      await client.sendCommand({
        command: 'abort',
        arguments: {},
        subscription: sessionId.value
      })

      ElMessage.success('Abort 命令已发送')
    } catch (e: any) {
      ElMessage.error(e?.message || '发送 abort 失败')
    }
  }

  const respondPermission = async (granted: boolean) => {
    if (!client) return
    try {
      await client.sendPermissionResponse({
        granted,
        requestId: permissionDialog.requestId,
        receiverId: permissionDialog.senderId || '',
        subscription: sessionId.value,
      })
    } catch (e: any) {
      ElMessage.error(e?.message || '权限响应失败')
    } finally {
      permissionDialog.visible = false
    }
  }

  const autoConnectAndSubscribe = async () => {
    if (!urlSessionId.value) {
      ElMessage.info('未提供session_id，请手动输入')
      return
    }

    sessionId.value = urlSessionId.value

    try {
      await fetchAgentId(urlSessionId.value)
      await doConnect()
      await doSubscribe()
      await loadHistory(urlSessionId.value)
      scrollToBottom()
    } catch (error: any) {
      console.error('自动连接失败:', error)
      ElMessage.error(`自动连接失败: ${error.message || '未知错误'}`)
    }
  }

  const init = async () => {
    await userStore.init()
    checkMobile()
    window.addEventListener('resize', checkMobile)

    if (urlSessionId.value) {
      autoConnectAndSubscribe()
    }
  }

  const cleanup = () => {
    window.removeEventListener('resize', checkMobile)
    if (client) {
      client.disconnect()
      client = null
    }
  }

  return {
    connected,
    connecting,
    sessionId,
    agentId,
    agentName,
    agentStatus,
    input,
    loading,
    loadingMore,
    hasMoreHistory,
    messagesContainer,
    showLeftSidebar,
    showRightSidebar,
    isMobile,
    messageFilters,
    urlSessionId,
    permissionDialog,
    socketConfig,
    uiMessages,
    filteredMessages,
    statusText,
    agentStatusText,
    scrollToBottom,
    toggleToolParameters,
    toggleLeftSidebar,
    toggleRightSidebar,
    addUiMessage,
    addSystemMessage,
    init,
    cleanup,
    sendUserMessage,
    sendAbort,
    respondPermission,
    doConnect,
    doSubscribe,
    loadHistory,
  }
})
