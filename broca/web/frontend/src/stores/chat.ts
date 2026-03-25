import { defineStore } from 'pinia'
import { ref, computed, reactive, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore, useAgentStore } from '@/stores'
import { BrocaSocketClient, type Message } from '@/api/brocaSocket'
import { sessionApi } from '@/api/session'

export const useChatStore = defineStore('chat', () => {
  const route = useRoute()
  const userStore = useUserStore()
  const agentStore = useAgentStore()

  const connected = ref(false)
  const connecting = ref(false)
  const connectingSession = ref(false) // 防止重复执行连接流程
  const sessionId = ref<string>('')
  const currentSessionId = ref('') // 跟踪当前订阅的sessionId
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

  // 代理到 agentStore（直接返回ref，模板自动解包）
  const agents = agentStore.agents
  const agentId = agentStore.currentAgentId
  const agentName = agentStore.currentAgentName
  const agentStatus = agentStore.currentAgentStatus

  const urlSessionId = computed(() => {
    return (route.params.session_id as string) || (route.query.session_id as string) || ''
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

  const statusText = computed(() => {
    if (connecting.value) return 'connecting'
    return connected.value ? 'connected' : 'disconnected'
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
    if (connected.value || connecting.value) return
    connecting.value = true
    agentStore.currentAgentStatus = 'connecting'
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
        agentStore.currentAgentStatus = 'idle'
        // 将所有agent状态重置为idle
        agentStore.agents = agentStore.agents.map((agent) => ({
          ...agent,
          status: 'idle',
        }))
      })
      client.on('disconnect', () => {
        connected.value = false
        connecting.value = false
        agentStore.currentAgentStatus = 'disconnected'
        // 将所有agent状态设置为disconnected
        agentStore.agents = agentStore.agents.map((agent) => ({
          ...agent,
          status: 'disconnected',
        }))
        console.log('Disconnected from server')
      })
      client.on('message', (m: Message) => {
        addMessage(m)
        scrollToBottom()
      })

      client.on('turn_start', (m: Message) => {
        agentStore.currentAgentStatus = 'running'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentStore.currentAgentId
        agentStore.updateAgentStatus(targetAgentId, 'running')
      })
      client.on('turn_end', (m: Message) => {
        agentStore.currentAgentStatus = 'idle'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentStore.currentAgentId
        agentStore.updateAgentStatus(targetAgentId, 'idle')
      })
      client.on('agent_response', (m: Message) => {
        agentStore.currentAgentStatus = 'running'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentStore.currentAgentId
        agentStore.updateAgentStatus(targetAgentId, 'running')
      })
      client.on('tool_call', (m: Message) => {
        agentStore.currentAgentStatus = 'running'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentStore.currentAgentId
        agentStore.updateAgentStatus(targetAgentId, 'running')
      })

      client.on('permission_request', (m: Message) => {
        permissionDialog.visible = true
        permissionDialog.requestId = m.data?.request_id
        permissionDialog.senderId = m.sender_id
        permissionDialog.message = m.data?.message || 'Permission required'
      })

      await client.connect()
    } catch (e: any) {
      connecting.value = false
      connected.value = false
      agentStore.currentAgentStatus = 'disconnected'
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

    // 解析@mention
    const { targetAgentId, cleanText } = parseMention(text)

    // 检查cleanText是否为空或只包含空格
    if (!cleanText.trim()) {
      ElMessage.warning('请输入消息内容')
      return
    }

    input.value = ''

    const targetAgent = targetAgentId || agentStore.currentAgentId

    // 获取目标agent的名称用于显示
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

    try {
      await client.sendUserMessage({
        content: cleanText,
        receiverId: targetAgent,
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

    if (agentStore.currentAgentStatus !== 'running') {
      ElMessage.info('Agent 未在运行中，无需 abort')
      return
    }

    try {
      await client.sendCommand({
        command: 'abort',
        arguments: {},
        subscription: sessionId.value,
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

  // 清理当前session的状态
  const cleanupSession = async () => {
    // 清理消息和状态
    messages.value = []
    messageStates.value.clear()
    pendingChunks.value.clear()
    agentStore.agents = []
    agentStore.currentAgentId = 'main_agent'
    agentStore.currentAgentName = 'Assistant'
    agentStore.currentAgentStatus = 'disconnected'
    currentSessionId.value = ''
  }

  const autoConnectAndSubscribe = async () => {
    if (!urlSessionId.value) {
      ElMessage.info('未提供session_id，请手动输入')
      return
    }

    // 防止重复执行相同的session连接
    if (connectingSession.value && currentSessionId.value === urlSessionId.value) {
      console.log('连接流程已在进行中，跳过')
      return
    }

    // 如果切换到了不同的session，先清理旧状态
    if (currentSessionId.value && currentSessionId.value !== urlSessionId.value) {
      await cleanupSession()
    }

    connectingSession.value = true
    currentSessionId.value = urlSessionId.value
    sessionId.value = urlSessionId.value

    try {
      await agentStore.fetchSessionAgents(urlSessionId.value, connected.value)
      await doConnect()
      await doSubscribe()
      await loadHistory(urlSessionId.value)
      scrollToBottom()
    } catch (error: any) {
      console.error('自动连接失败:', error)
      ElMessage.error(`自动连接失败: ${error.message || '未知错误'}`)
      // 失败时重置状态
      currentSessionId.value = ''
    } finally {
      connectingSession.value = false
    }
  }

  const init = async () => {
    await userStore.init()

    // 检查登录状态
    if (!userStore.isLoggedIn) {
      console.log('用户未登录，无法初始化聊天')
      return
    }

    checkMobile()
    window.addEventListener('resize', checkMobile)
    // 不再自动连接，由watch监听urlSessionId变化来触发
  }

  const cleanup = () => {
    window.removeEventListener('resize', checkMobile)
    if (client) {
      client.disconnect()
      client = null
    }
    // 清理所有状态
    connected.value = false
    connecting.value = false
    connectingSession.value = false
    sessionId.value = ''
    currentSessionId.value = ''
    agentStore.agents = []
    agentStore.currentAgentId = 'main_agent'
    agentStore.currentAgentName = 'Assistant'
    agentStore.currentAgentStatus = 'disconnected'
    messages.value = []
    messageStates.value.clear()
    pendingChunks.value.clear()
  }

  return {
    connected,
    connecting,
    connectingSession,
    sessionId,
    currentSessionId,
    agents,
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
    urlSessionId,
    permissionDialog,
    socketConfig,
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
