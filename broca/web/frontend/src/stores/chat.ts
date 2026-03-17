import { defineStore } from 'pinia'
import { ref, computed, reactive, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores'
import { BrocaSocketClient, type Message } from '@/api/brocaSocket'
import { sessionApi, type Agent as SessionAgent } from '@/api/session'


export type AgentStatus = 'idle' | 'running' | 'connecting' | 'disconnected'

// 使用SessionAgent类型
type Agent = SessionAgent

export const useChatStore = defineStore('chat', () => {
  const route = useRoute()
  const userStore = useUserStore()

  const connected = ref(false)
  const connecting = ref(false)
  const sessionId = ref<string>('')
  const agents = ref<Agent[]>([])
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

  const messages = ref<Message[]>([])
  const messageStates = ref<Map<string, { showParameters: boolean; showResult: boolean }>>(new Map())

  // 更新特定agent的状态
  const updateAgentStatus = (agentId: string, status: AgentStatus) => {
    const agentIndex = agents.value.findIndex(a => a.agent_id === agentId)
    if (agentIndex !== -1) {
      const agent = agents.value[agentIndex]
      if (agent) {
        // 创建新的agent对象以触发响应式更新
        const updatedAgent = { ...agent, status }
        agents.value.splice(agentIndex, 1, updatedAgent)
      }
    } else {
      // 如果agent不在列表中，可能是新创建的agent，尝试重新获取agents列表
      console.log(`Agent ${agentId} not found in list, refreshing agents...`)
      if (sessionId.value) {
        fetchSessionAgents(sessionId.value)
      }
    }
  }

  // 获取session中的所有agents
  const fetchSessionAgents = async (sessionId: string) => {
    try {
      const response = await sessionApi.getSessionAgents(sessionId)
      // 为每个agent设置默认状态
      const agentsWithStatus = response.map(agent => ({
        ...agent,
        status: (agent.status as AgentStatus) || (connected.value ? 'idle' : 'disconnected')
      }))
      agents.value = agentsWithStatus
      
      // 设置默认agent：优先选择role为main_agent或main-agent的，否则选择第一个agent
      const mainAgent = agentsWithStatus.find(agent => agent.role === 'main_agent' || agent.role === 'main-agent')
      if (mainAgent) {
        agentId.value = mainAgent.agent_id
        agentName.value = mainAgent.name || 'Main Agent'
      } else if (agentsWithStatus.length > 0) {
        const firstAgent = agentsWithStatus[0]
        if (firstAgent) {
          agentId.value = firstAgent.agent_id
          agentName.value = firstAgent.name || 'Assistant'
        } else {
          // 如果没有agent，使用默认值
          agentId.value = 'main_agent'
          agentName.value = 'Assistant'
        }
      } else {
        // 如果没有agent，使用默认值
        agentId.value = 'main_agent'
        agentName.value = 'Assistant'
      }
      
      agentStatus.value = 'idle'
    } catch (error: any) {
      console.error('获取session agents失败:', error)
      agentName.value = 'Assistant'
      agentStatus.value = 'disconnected'
    }
  }

  // 解析输入中的@mention，返回目标agentId
  const parseMention = (text: string): { targetAgentId: string | null, cleanText: string } => {
    // 如果agents列表为空，直接返回
    if (!agents.value || agents.value.length === 0) {
      return { targetAgentId: null, cleanText: text }
    }
  
    // 改进的正则表达式，支持中文、字母、数字、下划线和连字符
    // 匹配 @mention 或 @ mention（允许有空格）
    const mentionRegex = /@([\w\u4e00-\u9fa5\-]+)(?:\s|$)/
    const match = text.match(mentionRegex)

    if (match && match[1]) {
      const mentionName = match[1]
      const cleanText = text.replace(mentionRegex, '').trim()

      // 查找匹配的agent
      const targetAgent = agents.value.find(agent => {
        if (!agent) return false
        
        const agentNameLower = agent.name?.toLowerCase() || ''
        const mentionNameLower = mentionName.toLowerCase()
        
        // 检查name是否包含mentionName（支持部分匹配）
        if (agentNameLower && agentNameLower === mentionNameLower) {
          return true
        }
        return false
      })
            
      if (targetAgent) {
        return { targetAgentId: targetAgent.agent_id, cleanText }
      } else {
        console.log('未找到匹配的agent')
      }
    }

    // 如果文本只包含@符号，返回空字符串作为cleanText
    if (text.trim() === '@') {
      return { targetAgentId: null, cleanText: '' }
    }

    return { targetAgentId: null, cleanText: text.trim() }
  }

  const filteredMessages = computed(() => {
    return messages.value.filter(msg => {
      if (msg.message_type === 'user_message') {
        return messageFilters.showUser
      } else if (msg.message_type === 'agent_response') {
        return messageFilters.showAssistant
      } else if (msg.message_type === 'system_message' || msg.role === 'system') {
        return messageFilters.showSystem
      } else if (msg.message_type === 'error' || msg.message_type === 'agent_error') {
        return messageFilters.showError
      } else if (msg.message_type === 'tool_call') {
        return messageFilters.showAssistant
      }
      return true
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
    const currentState = messageStates.value.get(messageId)
    if (currentState) {
      messageStates.value.set(messageId, {
        ...currentState,
        showParameters: !currentState.showParameters
      })
    } else {
      messageStates.value.set(messageId, {
        showParameters: true,
        showResult: false
      })
    }
  }

  const toggleToolResult = (messageId: string) => {
    const currentState = messageStates.value.get(messageId)
    if (currentState) {
      messageStates.value.set(messageId, {
        ...currentState,
        showResult: !currentState.showResult
      })
    } else {
      messageStates.value.set(messageId, {
        showParameters: false,
        showResult: true
      })
    }
  }



  // 处理消息，决定是否显示
  const processMessage = (msg: any): Message | null => {
    const message = msg as Message
    
    // 过滤不需要显示的消息类型
    const filteredTypes = [
      'turn_start', 'turn_end', 'command', 'permission_request', 'permission_response',
      'subscribe', 'unsubscribe', 'connect', 'disconnect',
      'ping', 'pong', 'task_start', 'task_complete', 'task_error'
    ]
    
    if (filteredTypes.includes(message.message_type)) {
      return null
    }

    // 过滤连接/订阅相关的系统消息
    const contentStr = message.data?.content ?? ''
    if (typeof contentStr === 'string' && (
      contentStr.toLowerCase().includes('connected to') || 
      contentStr.toLowerCase().includes('subscribed to')
    )) {
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
      const existingIndex = messages.value.findIndex(msg => 
        msg.message_type === 'tool_call' && 
        msg.data?.tool_call_id === toolCallId
      )
      
      if (existingIndex !== -1) {
        // 合并消息：直接更新现有消息的data字段
        // 这样可以保持Vue的响应性
        const existingMessage = messages.value[existingIndex]
        
        // 合并data字段
        const mergedData = {
          ...existingMessage.data,
          ...message.data
        }
                
        // 直接更新现有消息的data字段
        // 在Vue 3中，我们需要确保触发响应式更新
        // 由于existingMessage是响应式对象，直接赋值会触发更新
        existingMessage.data = mergedData
        
        // 更新时间戳
        if (message.timestamp) {
          existingMessage.timestamp = message.timestamp
        }
        
        // 更新消息状态（保持原有的状态）
        if (!messageStates.value.has(existingMessage.message_id)) {
          messageStates.value.set(existingMessage.message_id, {
            showParameters: false,
            showResult: false
          })
        }
        
        return existingMessage
      } else {
        // 没有相同tool_call_id的消息，直接添加
        messages.value.push(message)
        // 初始化消息状态
        if (!messageStates.value.has(message.message_id)) {
          messageStates.value.set(message.message_id, {
            showParameters: false,
            showResult: false
          })
        }
        return message
      }
    } else {
      // 不是TOOL_CALL消息，直接添加
      messages.value.push(message)
      // 初始化消息状态
      if (!messageStates.value.has(message.message_id)) {
        messageStates.value.set(message.message_id, {
          showParameters: false,
          showResult: false
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
      data: { content }
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
        const countResponse = await sessionApi.getSessionMessages(sessionId, 0, 1)
        historyTotal.value = countResponse.total || 0
        skip = 0
      }
      
      const response = await sessionApi.getSessionMessages(sessionId, skip, limit)
      
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
          // 对于加载更多，需要将历史消息添加到现有消息前面
          // 并且需要处理合并（历史消息在前，新消息在后）
          const combinedMessages = [...historyMessages, ...messages.value]
          messages.value = []
          messageStates.value.clear()
          
          // 重新添加所有消息，确保TOOL_CALL消息正确合并
          combinedMessages.forEach(msg => {
            addMessageToList(msg)
          })
        } else {
          // 对于首次加载，直接设置消息
          messages.value = []
          messageStates.value.clear()
          historyMessages.forEach(msg => {
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
        // 将所有agent状态重置为idle
        agents.value = agents.value.map(agent => ({
          ...agent,
          status: 'idle'
        }))
        ElMessage.success('连接成功')
      })
      client.on('disconnect', () => {
        connected.value = false
        connecting.value = false
        agentStatus.value = 'disconnected'
        // 将所有agent状态设置为disconnected
        agents.value = agents.value.map(agent => ({
          ...agent,
          status: 'disconnected'
        }))
        ElMessage.warning('连接断开')
      })
      client.on('message', (m: Message) => {
        addMessage(m)
        scrollToBottom()
      })

      client.on('turn_start', (m: Message) => {
        agentStatus.value = 'running'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentId.value
        updateAgentStatus(targetAgentId, 'running')
      })
      client.on('turn_end', (m: Message) => {
        agentStatus.value = 'idle'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentId.value
        updateAgentStatus(targetAgentId, 'idle')
      })
      client.on('agent_response', (m: Message) => {
        agentStatus.value = 'running'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentId.value
        updateAgentStatus(targetAgentId, 'running')
      })
      client.on('tool_call', (m: Message) => {
        agentStatus.value = 'running'
        // 更新特定agent的状态
        const targetAgentId = m.sender_id || agentId.value
        updateAgentStatus(targetAgentId, 'running')
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

    // 解析@mention
    const { targetAgentId, cleanText } = parseMention(text)
    
    // 检查cleanText是否为空或只包含空格
    if (!cleanText.trim()) {
      ElMessage.warning('请输入消息内容')
      return
    }

    input.value = ''

    const targetAgent = targetAgentId || agentId.value

    // 获取目标agent的名称用于显示
    const targetAgentObj = agents.value.find(a => a.agent_id === targetAgent)
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
        mention: targetAgentId ? displayAgentName : undefined
      }
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
      await fetchSessionAgents(urlSessionId.value)
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
    
    // 检查登录状态
    if (!userStore.isLoggedIn) {
      console.log('用户未登录，无法初始化聊天')
      return
    }
    
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
    messageFilters,
    urlSessionId,
    permissionDialog,
    socketConfig,
    messages,
    messageStates,
    filteredMessages,
    statusText,
    agentStatusText,
    scrollToBottom,
    toggleToolParameters,
    toggleToolResult,
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
    fetchSessionAgents,
    parseMention,
  }
})
