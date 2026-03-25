import { defineStore } from 'pinia'
import { ref, computed, reactive, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore, useAgentStore, useSocketStore } from '@/stores'
import { type Message } from '@/api/brocaSocket'
import { sessionApi } from '@/api/session'

export const useChatStore = defineStore('chat', () => {
  const route = useRoute()
  const userStore = useUserStore()
  const agentStore = useAgentStore()
  const socketStore = useSocketStore()

  const connected = computed(() => socketStore.connected)
  const connecting = computed(() => socketStore.connecting)
  const connectingSession = ref(false)
  const sessionId = ref<string>('')
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


  const urlSessionId = computed(() => {
    return (route.params.session_id as string) || (route.query.session_id as string) || ''
  })

  const permissionDialog = reactive({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    message: '',
  })

  const messages = ref<Message[]>([])
  const messageStates = ref<Map<string, { showParameters: boolean; showResult: boolean; showReasoning: boolean }>>(
    new Map()
  )
  const pendingChunks = ref<Map<string, Message[]>>(new Map())

  const mergeAgentResponseChunks = (chunks: Message[]) => {
    const parsedChunks: Array<{ content: string; reasoning_content: string; index: number }> = []

    for (const chunk of chunks) {
      try {
        const data = JSON.parse(chunk.data?.content || '{}')
        if (data.content || data.reasoning_content) {
          parsedChunks.push({
            content: data.content || '',
            reasoning_content: data.reasoning_content || '',
            index: data.index || 0,
          })
        }
      } catch {}
    }

    parsedChunks.sort((a, b) => a.index - b.index)

    let mergedContent = ''
    let mergedReasoning = ''

    for (const chunk of parsedChunks) {
      mergedContent += chunk.content
      mergedReasoning += chunk.reasoning_content
    }

    return {
      content: mergedContent,
      reasoning_content: mergedReasoning,
      index: 0,
    }
  }

  // 解析输入中的@mention - 代理到 agentStore
  const parseMention = (text: string) => {
    return agentStore.parseMention(text)
  }

  const statusText = computed(() => socketStore.statusText)

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
    const currentState = messageStates.value.get(messageId)
    if (currentState) {
      messageStates.value.set(messageId, {
        ...currentState,
        showParameters: !currentState.showParameters,
      })
    } else {
      messageStates.value.set(messageId, {
        showParameters: true,
        showResult: false,
        showReasoning: false,
      })
    }
  }

  const toggleToolResult = (messageId: string) => {
    const currentState = messageStates.value.get(messageId)
    if (currentState) {
      messageStates.value.set(messageId, {
        ...currentState,
        showResult: !currentState.showResult,
      })
    } else {
      messageStates.value.set(messageId, {
        showParameters: false,
        showResult: true,
        showReasoning: false,
      })
    }
  }

  const toggleReasoning = (messageId: string) => {
    const currentState = messageStates.value.get(messageId)
    if (currentState) {
      messageStates.value.set(messageId, {
        ...currentState,
        showReasoning: !currentState.showReasoning,
      })
    } else {
      messageStates.value.set(messageId, {
        showParameters: false,
        showResult: false,
        showReasoning: true,
      })
    }
  }

  // 处理消息，决定是否显示
  const processMessage = (msg: any): Message | null => {
    const message = msg as Message

    // 过滤不需要显示的消息类型
    const filteredTypes = [
      'turn_start',
      'turn_end',
      'command',
      'permission_request',
      'permission_response',
      'subscribe',
      'unsubscribe',
      'connect',
      'disconnect',
      'ping',
      'pong',
      'task_start',
      'task_complete',
      'task_error',
    ]

    if (filteredTypes.includes(message.message_type)) {
      return null
    }

    if (message.message_type === 'user_message' && message.data?.from_agent) {
      return null
    }

    const contentStr = message.data?.content ?? ''

    if (message.message_type === 'agent_response' && typeof contentStr === 'string') {
      const parsed = JSON.parse(contentStr)
      if (
        (parsed.content === null || parsed.content === undefined || parsed.content === '') &&
        (parsed.reasoning_content === null || parsed.reasoning_content === undefined || parsed.reasoning_content === '')
      ) {
        return null
      }
    }

    if (
      typeof contentStr === 'string' &&
      (contentStr.toLowerCase().includes('connected to') || contentStr.toLowerCase().includes('subscribed to'))
    ) {
      return null
    }

    return message
  }

  // 添加消息到列表，处理TOOL_CALL消息的合并
  const addMessageToList = (message: Message) => {
    // 如果是TOOL_CALL消息，检查是否有相同tool_call_id的消息需要合并
    if (message.message_type === 'tool_call' && message.data?.tool_call_id) {
      const toolCallId = message.data.tool_call_id

      // 查找是否已经存在相同tool_call_id的消息
      const existingIndex = messages.value.findIndex(
        (msg) => msg.message_type === 'tool_call' && msg.data?.tool_call_id === toolCallId
      )

      if (existingIndex !== -1) {
        // 合并消息：直接更新现有消息的data字段
        // 这样可以保持Vue的响应性
        const existingMessage = messages.value[existingIndex]
        if (!existingMessage) return message

        // 合并data字段
        const mergedData = {
          ...existingMessage.data,
          ...message.data,
        }

        existingMessage.data = mergedData

        // 更新时间戳
        if (message.timestamp) {
          existingMessage.timestamp = message.timestamp
        }

        return existingMessage
      } else {
        // 没有相同tool_call_id的消息，直接添加
        messages.value.push(message)
        // 初始化消息状态
        if (!messageStates.value.has(message.message_id)) {
          messageStates.value.set(message.message_id, {
            showParameters: false,
            showResult: false,
            showReasoning: false,
          })
        }
        return message
      }
    } else if (message.message_type === 'agent_response') {
      const msgId = message.message_id

      // 收集所有chunk
      if (!pendingChunks.value.has(msgId)) {
        pendingChunks.value.set(msgId, [])
      }
      pendingChunks.value.get(msgId)!.push(message)

      // 合并内容
      const chunks = pendingChunks.value.get(msgId)!
      const merged = mergeAgentResponseChunks(chunks)

      // 检查是否已存在该message_id的消息
      const existingIndex = messages.value.findIndex(
        (msg) => msg.message_type === 'agent_response' && msg.message_id === msgId
      )

      if (existingIndex !== -1) {
        const existingMessage = messages.value[existingIndex]
        if (!existingMessage) {
          const copy = JSON.parse(JSON.stringify(message))
          messages.value.push(copy)
          return message
        }
        existingMessage.data = {
          ...existingMessage.data,
          content: JSON.stringify(merged, null, 0),
        }

        // 更新时间戳
        if (message.timestamp) {
          existingMessage.timestamp = message.timestamp
        }

        return existingMessage
      } else {
        // 首次收到，加入消息的拷贝
        const copy = JSON.parse(JSON.stringify(message))
        messages.value.push(copy)
      }

      if (!messageStates.value.has(message.message_id)) {
        messageStates.value.set(message.message_id, {
          showParameters: false,
          showResult: false,
          showReasoning: false,
        })
      }

      return message
    } else {
      messages.value.push(message)
      // 初始化消息状态
      if (!messageStates.value.has(message.message_id)) {
        messageStates.value.set(message.message_id, {
          showParameters: false,
          showResult: false,
          showReasoning: false,
        })
      }
      return message
    }
  }

  const addMessage = (m: Message) => {
    const processed = processMessage(m)
    if (processed) {
      addMessageToList(processed)
    }
  }

  const addSystemMessage = (content: string) => {
    const msg: Message = {
      message_id: `system_${Date.now()}`,
      message_type: 'system_message',
      timestamp: new Date().toISOString(),
      role: 'system',
      sender_id: 'system',
      data: { content },
    }
    addMessageToList(msg)
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
      messages.value = []
    }

    try {
      let skip: number
      if (isLoadMore) {
        skip = historySkip.value
      } else {
        skip = 0
      }

      const response = await sessionApi.getSessionMessages(sessionId, skip, limit)
      historyTotal.value = response.total

      if (response.messages) {
        const allMessages = response.messages

        const historyMessages: Message[] = []

        allMessages.forEach((msg: any) => {
          const processed = processMessage(msg)
          if (processed) {
            historyMessages.push(processed)
          }
        })

        if (isLoadMore) {
          const combinedMessages = [...historyMessages, ...messages.value]
          messages.value = []
          messageStates.value.clear()

          // 重新添加所有消息，确保TOOL_CALL消息正确合并
          combinedMessages.forEach((msg) => {
            addMessageToList(msg)
          })
        } else {
          // 对于首次加载，直接设置消息
          messages.value = []
          messageStates.value.clear()
          historyMessages.forEach((msg) => {
            addMessageToList(msg)
          })
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

    socketStore.onConnect = () => {
      agentStore.agents = agentStore.agents.map((agent) => ({
        ...agent,
        status: 'idle',
      }))
    }
    socketStore.onDisconnect = () => {
      agentStore.agents = agentStore.agents.map((agent) => ({
        ...agent,
        status: 'disconnected',
      }))
      console.log('Disconnected from server')
    }
    socketStore.onMessage = (m: Message) => {
      addMessage(m)
      scrollToBottom()
    }
    socketStore.onTurnStart = (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'running')
    }
    socketStore.onTurnEnd = (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'idle')
    }
    socketStore.onAgentResponse = (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'running')
    }
    socketStore.onToolCall = (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'running')
    }
    socketStore.onPermissionRequest = (m: Message) => {
      permissionDialog.visible = true
      permissionDialog.requestId = m.data?.request_id
      permissionDialog.senderId = m.sender_id
      permissionDialog.message = m.data?.message || 'Permission required'
    }

    await socketStore.connect()
  }

  const doSubscribe = async () => {
    await socketStore.subscribe(sessionId.value)
  }

  const sendUserMessage = async () => {
    const text = input.value.trim()
    if (!text) return

    const { targetAgentId, cleanText } = parseMention(text)

    if (!cleanText.trim()) {
      return
    }

    input.value = ''

    const targetAgent = targetAgentId || agentStore.currentAgentId

    const targetAgentObj = agentStore.agents.find((a: any) => a.agent_id === targetAgent)
    const displayAgentName = targetAgentObj?.name || targetAgent

    addMessage({
      message_id: `user_${Date.now()}`,
      timestamp: new Date().toISOString(),
      message_type: 'user_message',
      role: 'user',
      sender_id: 'user',
      receiver_id: targetAgent,
      subscription: sessionId.value,
      data: {
        content: cleanText,
        mention: targetAgentId ? displayAgentName : undefined,
      },
    } as Message)

    await socketStore.sendUserMessage({
      content: cleanText,
      receiverId: targetAgent,
      subscription: sessionId.value,
    })
  }

  const sendAbort = async (agentId?: string) => {
    // 如果指定了agentId，检查该agent的状态
    let targetAgentId = agentId
    if (!targetAgentId) {
      // 如果没有指定，使用当前agent
      targetAgentId = agentStore.currentAgentId
    }

    const targetAgent = agentStore.agents.find((a: any) => a.agent_id === targetAgentId)
    if (!targetAgent || targetAgent.status !== 'running') {
      return
    }

    await socketStore.sendAbort({
      receiverId: targetAgentId
    })

    // // 更新agent状态为idle
    // agentStore.updateAgentStatus(targetAgentId, 'idle')
  }

  const respondPermission = async (granted: boolean) => {
    await socketStore.respondPermission({
      granted,
      requestId: permissionDialog.requestId,
      receiverId: permissionDialog.senderId || '',
      subscription: sessionId.value,
    })
    permissionDialog.visible = false
  }

  // 清理当前session的状态
  const cleanupSession = async () => {
    // 清理消息和状态
    messages.value = []
    messageStates.value.clear()
    pendingChunks.value.clear()
    agentStore.agents = []
  }

  const autoConnectAndSubscribe = async () => {
    if (!urlSessionId.value) {
      return
    }

    if (connectingSession.value && sessionId.value === urlSessionId.value) {
      console.log('连接流程已在进行中，跳过')
      return
    }

    if (sessionId.value && sessionId.value !== urlSessionId.value) {
      await cleanupSession()
    }

    connectingSession.value = true
    sessionId.value = urlSessionId.value

    try {
      await agentStore.fetchAgents(urlSessionId.value, connected.value)
      await doConnect()
      await doSubscribe()
      await loadHistory(urlSessionId.value)
      scrollToBottom()
    } catch (error: any) {
      console.error('自动连接失败:', error)
      sessionId.value = ''
    } finally {
      connectingSession.value = false
    }
  }

  const init = async () => {
    await userStore.init()

    if (!userStore.isLoggedIn) {
      console.log('用户未登录，无法初始化聊天')
      return
    }

    checkMobile()
    window.addEventListener('resize', checkMobile)
  }

  const cleanup = () => {
    window.removeEventListener('resize', checkMobile)
    socketStore.cleanup()
    connectingSession.value = false
    sessionId.value = ''
    agentStore.agents = []
    messages.value = []
    messageStates.value.clear()
    pendingChunks.value.clear()
  }

  return {
    connected,
    connecting,
    connectingSession,
    sessionId,
    input,
    loading,
    loadingMore,
    hasMoreHistory,
    messagesContainer,
    showLeftSidebar,
    showRightSidebar,
    isMobile,
    urlSessionId,
    permissionDialog,
    messages,
    messageStates,
    pendingChunks,
    statusText,
    scrollToBottom,
    toggleToolParameters,
    toggleToolResult,
    toggleReasoning,
    toggleLeftSidebar,
    toggleRightSidebar,
    addMessage,
    addSystemMessage,
    init,
    cleanup,
    sendUserMessage,
    sendAbort,
    respondPermission,
    doConnect,
    doSubscribe,
    loadHistory,
    parseMention,
    autoConnectAndSubscribe,
    cleanupSession,
  }
})
