import { defineStore } from 'pinia'
import { ref, computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useAgentStore, useSocketStore } from '@/stores'
import { type Message } from '@/api/brocaSocket'
import { sessionApi, type RunnerInfo } from '@/api/session'

export const useChatStore = defineStore('chat', () => {
  const route = useRoute()
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

  // 撤销/重做相关状态
  const showRedoButton = ref(false)
  const redoReceiverId = ref<string | undefined>()

  // Runner 状态
  const runnerInfo = ref<RunnerInfo | null>(null)
  const runnerLoading = ref(false)
  const restartingRunner = ref(false)
  const stoppingRunner = ref(false)
  let runnerPollTimer: ReturnType<typeof setInterval> | null = null

  const runnerAlive = computed(() => {
    return runnerInfo.value?.status === 'alive'
  })

  const fetchRunnerStatus = async () => {
    if (!sessionId.value) return
    try {
      runnerLoading.value = true
      const data = await sessionApi.getRunnerStatus(sessionId.value)
      runnerInfo.value = data
    } catch (error) {
      console.error('获取Runner状态失败:', error)
    } finally {
      runnerLoading.value = false
    }
  }

  const restartRunner = async () => {
    if (!sessionId.value) return
    try {
      restartingRunner.value = true
      const { ElMessage } = await import('element-plus')
      await sessionApi.restartRunner(sessionId.value)
      ElMessage.success('进程重启成功')
      // 延迟刷新状态
      setTimeout(fetchRunnerStatus, 3000)
    } catch (error: any) {
      const { ElMessage } = await import('element-plus')
      ElMessage.error('重启失败: ' + (error.message || '未知错误'))
    } finally {
      restartingRunner.value = false
    }
  }

  const stopRunner = async () => {
    if (!sessionId.value) return
    try {
      stoppingRunner.value = true
      const { ElMessage } = await import('element-plus')
      await sessionApi.stopRunner(sessionId.value)
      ElMessage.success('进程已停止')
      runnerInfo.value = { ...runnerInfo.value!, status: 'dead' } as RunnerInfo
    } catch (error: any) {
      const { ElMessage } = await import('element-plus')
      ElMessage.error('停止失败: ' + (error.message || '未知错误'))
    } finally {
      stoppingRunner.value = false
      // 延迟刷新状态
      setTimeout(fetchRunnerStatus, 3000)
    }
  }

  const startRunnerPolling = () => {
    stopRunnerPolling()
    runnerPollTimer = setInterval(fetchRunnerStatus, 10000)
  }

  const stopRunnerPolling = () => {
    if (runnerPollTimer) {
      clearInterval(runnerPollTimer)
      runnerPollTimer = null
    }
  }

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

  const agentQueryDialog = reactive({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    question: '',
    options: [] as Array<{ name: string; description: string }>,
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
      'agent_query',
      'user_answer',
      'subscribe',
      'unsubscribe',
      'connect',
      'disconnect',
      'ping',
      'pong',
      'task_start',
      'task_complete',
      'task_error',
      'step_start',        // Step管理消息不显示
      'step_end',          // Step管理消息不显示
    ]

    if (filteredTypes.includes(message.message_type)) {
      return null
    }

    // 已撤销的消息不显示
    if (message.reverted) {
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

        // 更新message_id
        existingMessage.message_id = message.message_id

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
          const newMessages = [...historyMessages, ...messages.value]
          messages.value.splice(0, messages.value.length, ...newMessages)

          messageStates.value.clear()
          newMessages.forEach((msg) => {
            messageStates.value.set(msg.message_id, {
              showParameters: false,
              showResult: false,
              showReasoning: false,
            })
          })
        } else {
          messages.value = historyMessages
          messageStates.value.clear()
          historyMessages.forEach((msg) => {
            messageStates.value.set(msg.message_id, {
              showParameters: false,
              showResult: false,
              showReasoning: false,
            })
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
      // 如果是撤销或重做的结果，显示提示并重新加载消息
      if (m.message_type === 'command_result' && (m.data?.command === 'undo' || m.data?.command === 'redo')) {
        const result = m.data?.result
        if (result.code == 0) {
          if (m.data?.command === 'undo') {
            // 撤销成功后，显示重做按钮
            showRedoButton.value = true
            redoReceiverId.value = m.sender_id
            loadHistory(sessionId.value, false)
          } else {
            // 重做成功后，隐藏重做按钮
            showRedoButton.value = false
            redoReceiverId.value = undefined
            loadHistory(sessionId.value, false)
          }
        }
        return
      }

      // 如果是新消息（非命令结果），清除重做状态
      if (m.message_type !== 'command_result') {
        showRedoButton.value = false
        redoReceiverId.value = undefined
      }

      // 正常处理其他消息
      addMessage(m)
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
      // 收到 agent_response 时隐藏对话框
      permissionDialog.visible = false
      agentQueryDialog.visible = false
    }
    socketStore.onToolCall = (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'running')
      // 收到 tool_call 时隐藏对话框
      permissionDialog.visible = false
      agentQueryDialog.visible = false
    }
    socketStore.onPermissionRequest = (m: Message) => {
      permissionDialog.visible = true
      permissionDialog.requestId = m.data?.request_id
      permissionDialog.senderId = m.sender_id
      permissionDialog.message = m.data?.message || 'Permission required'
    }

    socketStore.onAgentQuery = (m: Message) => {
      agentQueryDialog.visible = true
      agentQueryDialog.requestId = m.data?.request_id
      agentQueryDialog.senderId = m.sender_id
      agentQueryDialog.question = m.data?.question || m.data?.content || ''
      agentQueryDialog.options = m.data?.options || []
    }

    await socketStore.connect()
  }

  const doSubscribe = async () => {
    await socketStore.subscribe(sessionId.value)
  }

  const sendUserMessage = async (
    content?: string,
    targetAgentId?: string,
    files?: Array<{
      name: string
      url: string
      path: string
      size: number
      type: string
      upload_time: string
    }>
  ) => {
    // 如果传入了参数，使用参数；否则从 input 获取（兼容旧调用）
    let text = content ?? input.value.trim()
    if (!text && (!files || files.length === 0)) return

    // 如果没有传入 targetAgentId，从 input 解析
    let parsedTargetAgentId: string | null | undefined = targetAgentId
    let cleanText = text
    if (!targetAgentId) {
      const parsed = parseMention(text)
      parsedTargetAgentId = parsed.targetAgentId
      cleanText = parsed.cleanText
    }

    if (!cleanText.trim() && (!files || files.length === 0)) {
      return
    }

    // 清空输入框（只在从 input 获取内容时）
    if (!content) {
      input.value = ''
    }

    const targetAgent = parsedTargetAgentId || agentStore.currentAgentId

    const targetAgentObj = agentStore.agents.find((a: any) => a.agent_id === targetAgent)
    const displayAgentName = targetAgentObj?.name || targetAgent

    // 构建消息 data
    const messageData: any = {
      content: cleanText,
    }

    // 添加 mention（如果有）
    if (parsedTargetAgentId) {
      messageData.mention = displayAgentName
    }

    // 添加 files（如果有）
    if (files && files.length > 0) {
      messageData.files = files
    }

    const messageId = `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`

    // 乐观更新
    addMessage({
      message_id: messageId,
      message_type: 'user_message',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: 'user',
      receiver_id: targetAgent,
      data: messageData,
    })

    // 发给agent
    await socketStore.sendUserMessage({
      messageId: messageId,
      content: cleanText,
      receiverId: targetAgent,
      files: files,
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
      receiverId: targetAgentId,
    })
  }

  const respondPermission = async (granted: boolean) => {
    await socketStore.respondPermission({
      granted,
      requestId: permissionDialog.requestId,
      receiverId: permissionDialog.senderId || '',
      subscription: sessionId.value ? String(sessionId.value) : undefined,
    })
    permissionDialog.visible = false
  }

  const respondUserAnswer = async (answer: string) => {
    await socketStore.sendUserAnswer({
      answer,
      requestId: agentQueryDialog.requestId,
      receiverId: agentQueryDialog.senderId || '',
    })
    agentQueryDialog.visible = false
  }

  // 清理当前session的状态
  const cleanupSession = async () => {
    // 清理消息和状态
    messages.value = []
    messageStates.value.clear()
    pendingChunks.value.clear()
    agentStore.agents = []
    // 清理 Runner 状态
    stopRunnerPolling()
    runnerInfo.value = null
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
      await agentStore.fetchAgents(urlSessionId.value)
      await doConnect()
      await doSubscribe()
      await loadHistory(urlSessionId.value)
      // 获取 Runner 状态并启动轮询
      await fetchRunnerStatus()
      startRunnerPolling()
    } catch (error: any) {
      console.error('自动连接失败:', error)
      sessionId.value = ''
    } finally {
      connectingSession.value = false
    }
  }

  const init = async () => {
    // await userStore.init()

    // if (!userStore.isLoggedIn) {
    //   console.log('用户未登录，无法初始化聊天')
    //   return
    // }

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
    showRedoButton,
    redoReceiverId,
    messagesContainer,
    showLeftSidebar,
    showRightSidebar,
    isMobile,
    urlSessionId,
    permissionDialog,
    agentQueryDialog,
    messages,
    messageStates,
    pendingChunks,
    statusText,
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
    respondUserAnswer,
    doConnect,
    doSubscribe,
    loadHistory,
    parseMention,
    autoConnectAndSubscribe,
    cleanupSession,
    // Runner 状态
    runnerInfo,
    runnerLoading,
    restartingRunner,
    runnerAlive,
    fetchRunnerStatus,
    restartRunner,
    // 停止 Runner
    stoppingRunner,
    stopRunner,
  }
})
