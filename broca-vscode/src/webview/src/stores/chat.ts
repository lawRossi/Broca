import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { postMessage, onMessage, getInitialData } from '../api/vscode'
import type { Message, RunnerInfo } from '../types'

export const useChatStore = defineStore('chat', () => {
  const sessionId = ref(getInitialData()?.sessionId || '')
  const connected = ref(false)
  const messages = ref<Message[]>([])
  const loading = ref(false)
  const loadingMore = ref(false)
  const hasMoreHistory = ref(true)
  const historySkip = ref(0)
  const historyTotal = ref(0)
  const runnerInfo = ref<RunnerInfo | null>(null)
  const inputText = ref('')
  const defaultAgentId = ref<string | undefined>(undefined)
  const agentNames = ref<Record<string, string>>({})

  // ==================== 完整 Agent 数据 ====================
  interface AgentInfo {
    agent_id: string
    name: string
    role?: string
    type?: string
    description?: string
    status?: string
    config_id?: string
    total_input_tokens?: number
    total_output_tokens?: number
    total_llm_calls?: number
    last_context_length?: number
  }
  const agents = ref<AgentInfo[]>([])

  // ==================== Agent 运行时状态追踪 ====================
  // 根据 turn_start / turn_end / agent_response / tool_call 消息更新
  type AgentStatus = 'idle' | 'running' | 'connecting' | 'disconnected'
  const agentStatuses = ref<Record<string, AgentStatus>>({})

  function updateAgentStatus(agentId: string | undefined, status: AgentStatus) {
    if (!agentId) return
    agentStatuses.value = { ...agentStatuses.value, [agentId]: status }
  }

  function getAgentStatus(agentId: string | undefined): AgentStatus {
    if (!agentId) return 'disconnected'
    return agentStatuses.value[agentId] || 'disconnected'
  }

  // 获取 Agent 在 agents 数组中的运行时状态（合并 agentStatuses）
  function getAgentRuntimeStatus(agentId: string | undefined): AgentStatus {
    return getAgentStatus(agentId)
  }

  // ==================== 侧栏状态 ====================
  const showLeftSidebar = ref(true)
  const showRightSidebar = ref(true)
  const isMobile = ref(false)

  function toggleLeftSidebar() {
    showLeftSidebar.value = !showLeftSidebar.value
    if (showLeftSidebar.value) showRightSidebar.value = false
  }

  function toggleRightSidebar() {
    showRightSidebar.value = !showRightSidebar.value
    if (showRightSidebar.value) showLeftSidebar.value = false
  }

  // ==================== 消息状态管理 ====================
  const messageStates = ref<Map<string, {
    showParameters: boolean
    showResult: boolean
    showReasoning: boolean
  }>>(new Map())

  function getMessageState(messageId: string) {
    let state = messageStates.value.get(messageId)
    if (!state) {
      state = { showParameters: false, showResult: false, showReasoning: false }
      messageStates.value.set(messageId, state)
    }
    return state
  }

  function toggleToolParameters(messageId: string) {
    const state = getMessageState(messageId)
    state.showParameters = !state.showParameters
  }

  function toggleToolResult(messageId: string) {
    const state = getMessageState(messageId)
    state.showResult = !state.showResult
  }

  function toggleReasoning(messageId: string) {
    const state = getMessageState(messageId)
    state.showReasoning = !state.showReasoning
  }

  // Permission dialog state
  const permissionDialog = ref({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    message: '',
  })

  // Agent query dialog state
  const agentQueryDialog = ref({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    question: '',
    options: [] as Array<{ name: string; description: string }>,
  })

  // Undo/Redo state
  const showRedoButton = ref(false)
  const redoReceiverId = ref<string | undefined>()

  const runnerAlive = computed(() => runnerInfo.value?.status === 'alive')

  // ==================== 消息处理 ====================
  // 消息合并池：agent_response 的流式 chunk 按 message_id 收集
  const pendingChunks = ref<Map<string, Message[]>>(new Map())

  function mergeAgentResponseChunks(chunks: Message[]) {
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

    return { content: mergedContent, reasoning_content: mergedReasoning, index: 0 }
  }

  // Initialize: listen for messages from extension host
  function init() {
    console.log('[ChatStore] init, sessionId:', sessionId.value, 'connected:', connected.value)
    
    onMessage((data: any) => {
      console.log('[ChatStore] received from extension:', data.type)
      switch (data.type) {
        case 'connected':
          connected.value = data.payload.connected
          break

        case 'agents':
          defaultAgentId.value = data.payload.defaultAgentId
          // Store full agent data
          agents.value = (data.payload.agents || []).map((a: any) => ({
            agent_id: a.agent_id,
            name: a.name || a.agent_id,
            role: a.role,
            type: a.type || 'assistant',
            description: a.description,
            status: a.status,
            config_id: a.config_id,
            total_input_tokens: a.total_input_tokens,
            total_output_tokens: a.total_output_tokens,
            total_llm_calls: a.total_llm_calls,
            last_context_length: a.last_context_length,
          }))
          // Build agent name map (for backward compatibility)
          const names: Record<string, string> = {}
          for (const agent of agents.value) {
            names[agent.agent_id] = agent.name
          }
          agentNames.value = names
          break

        case 'message':
          handleIncomingMessage(data.payload)
          break

        case 'historyLoaded':
          handleHistoryLoaded(data.payload)
          break

        case 'runnerStatus':
          runnerInfo.value = data.payload
          break

        case 'error':
          console.error('Extension error:', data.payload.message)
          break
      }
    })

    // Notify extension that WebView is ready
    postMessage({ type: 'ready' })
  }

  function handleIncomingMessage(message: Message) {
    // Debug: log agent_response content
    if (message.message_type === 'agent_response') {
      console.log('[ChatStore] agent_response received:', {
        message_id: message.message_id,
        contentType: typeof message.data?.content,
        contentRaw: message.data?.content?.substring?.(0, 100),
        dataKeys: Object.keys(message.data || {}),
      })
    }

    // ===== 弹窗类消息：在 processMessage 之前处理，避免被过滤掉 =====
    // Check if it's a permission request
    if (message.message_type === 'permission_request') {
      permissionDialog.value = {
        visible: true,
        requestId: message.data?.request_id,
        senderId: message.sender_id,
        message: message.data?.message || 'Permission required',
      }
      return
    }

    // Check if it's an agent query
    if (message.message_type === 'agent_query') {
      agentQueryDialog.value = {
        visible: true,
        requestId: message.data?.request_id,
        senderId: message.sender_id,
        question: message.data?.question || message.data?.content || '',
        options: message.data?.options || [],
      }
      return
    }

    // ===== Agent 运行状态更新：在 processMessage 之前处理，因为这些消息类型会被过滤掉 =====
    if (message.message_type === 'turn_start') {
      const targetAgentId = message.sender_id || message.agent_id || defaultAgentId.value
      updateAgentStatus(targetAgentId, 'running')
      return  // turn_start 不需要显示在消息列表中
    }

    if (message.message_type === 'turn_end') {
      const targetAgentId = message.sender_id || message.agent_id || defaultAgentId.value
      updateAgentStatus(targetAgentId, 'idle')
      return  // turn_end 不需要显示在消息列表中
    }

    // agent_response 和 tool_call 也更新 Agent 状态为 running
    if (message.message_type === 'agent_response' || message.message_type === 'tool_call') {
      const targetAgentId = message.sender_id || message.agent_id || defaultAgentId.value
      updateAgentStatus(targetAgentId, 'running')
    }

    // Process/filter message
    const processed = processMessage(message)
    if (!processed) {
      if (message.message_type === 'agent_response') {
        console.log('[ChatStore] agent_response FILTERED OUT')
      }
      return
    }

    if (message.message_type === 'agent_response') {
      console.log('[ChatStore] agent_response PASSED filter, adding to list')
    }

    // Handle undo/redo results
    if (message.message_type === 'command_result') {
      if (message.data?.command === 'undo') {
        showRedoButton.value = true
        redoReceiverId.value = message.sender_id
        loadHistory(0, 50)
        return
      } else if (message.data?.command === 'redo') {
        showRedoButton.value = false
        redoReceiverId.value = undefined
        return
      }
    }

    // Clear redo state for new messages
    if (message.message_type !== 'command_result') {
      showRedoButton.value = false
      redoReceiverId.value = undefined
    }

    // Add message to list
    addMessage(message)
  }

  /**
   * Filter messages, returns null for messages that should not be displayed.
   * Mirrors web version's processMessage() in chat store.
   */
  function processMessage(msg: Message): Message | null {
    // Filter out internal message types
    const filteredTypes = [
      'turn_start', 'turn_end', 'command',
      'permission_request', 'permission_response',
      'agent_query', 'user_answer',
      'subscribe', 'unsubscribe', 'connect', 'disconnect',
      'ping', 'pong',
      'task_start', 'task_complete', 'task_error',
      'step_start', 'step_end',
    ]
    if (filteredTypes.includes(msg.message_type)) return null

    // Filter reverted messages
    if ((msg as any).reverted) return null

    // Filter user messages from agent
    if (msg.message_type === 'user_message' && msg.data?.from_agent) return null

    // Filter empty agent responses (where content and reasoning_content are both empty)
    if (msg.message_type === 'agent_response') {
      const contentStr = msg.data?.content ?? ''
      if (typeof contentStr === 'string') {
        try {
          const parsed = JSON.parse(contentStr)
          const empty = (
            (parsed.content === null || parsed.content === undefined || parsed.content === '') &&
            (parsed.reasoning_content === null || parsed.reasoning_content === undefined || parsed.reasoning_content === '')
          )
          if (empty) return null
          // Fix: if content is a nested JSON string, unwrap it
          if (typeof parsed.content === 'string' && parsed.content.startsWith('{')) {
            try {
              const inner = JSON.parse(parsed.content)
              if (inner.content) parsed.content = inner.content
            } catch {}
          }
        } catch {
          // If parsing fails, show the message as-is
        }
      }
    }

    // Filter connection/subscription system messages
    const contentStr = msg.data?.content ?? ''
    if (typeof contentStr === 'string') {
      const lower = contentStr.toLowerCase()
      if (lower.includes('connected to') || lower.includes('subscribed to')) return null
    }

    // For user messages: if content looks like JSON with a nested content field, unwrap it
    if (msg.message_type === 'user_message' && typeof contentStr === 'string' && contentStr.startsWith('{')) {
      try {
        const parsed = JSON.parse(contentStr)
        if (parsed.content) {
          msg.data.content = parsed.content
        }
      } catch {}
    }

    return msg
  }

  function handleHistoryLoaded(payload: {
    messages: Message[]
    total: number
    skip: number
    limit: number
  }) {
    // Filter history messages through processMessage
    const filtered = (payload.messages || []).filter(m => processMessage(m) !== null)

    if (payload.skip === 0) {
      // Initial load - replace all messages
      messages.value = filtered
    } else {
      // Load more - prepend to existing messages
      const newMessages = [...filtered, ...messages.value]
      messages.value = newMessages
    }

    historySkip.value = payload.skip + payload.limit
    historyTotal.value = payload.total
    hasMoreHistory.value = historySkip.value < historyTotal.value
    loading.value = false
    loadingMore.value = false

    // Initialize message states for all messages
    for (const msg of messages.value) {
      getMessageState(msg.message_id)
    }
  }

  function addMessage(message: Message) {
    // Handle tool_call merging
    if (message.message_type === 'tool_call' && message.data?.tool_call_id) {
      const existingIndex = messages.value.findIndex(
        (m) => m.message_type === 'tool_call' && m.data?.tool_call_id === message.data?.tool_call_id
      )
      if (existingIndex !== -1) {
        messages.value[existingIndex] = {
          ...messages.value[existingIndex],
          data: { ...messages.value[existingIndex].data, ...message.data },
          timestamp: message.timestamp,
        }
        getMessageState(message.message_id)
        return
      }
    }

    // Handle agent_response chunk merging using pendingChunks pool
    if (message.message_type === 'agent_response') {
      const msgId = message.message_id

      // Collect chunks
      if (!pendingChunks.value.has(msgId)) {
        pendingChunks.value.set(msgId, [])
      }
      pendingChunks.value.get(msgId)!.push(message)

      // Merge content
      const chunks = pendingChunks.value.get(msgId)!
      const merged = mergeAgentResponseChunks(chunks)

      // Check if already exists
      const existingIndex = messages.value.findIndex(
        (msg) => msg.message_type === 'agent_response' && msg.message_id === msgId
      )

      if (existingIndex !== -1) {
        messages.value[existingIndex] = {
          ...messages.value[existingIndex],
          data: {
            ...messages.value[existingIndex].data,
            content: JSON.stringify(merged),
          },
          timestamp: message.timestamp,
        }
        return
      } else {
        // First chunk: push a copy
        const copy = JSON.parse(JSON.stringify(message))
        copy.data.content = JSON.stringify(merged)
        messages.value.push(copy)
      }

      getMessageState(message.message_id)
      return
    }

    messages.value.push(message)
    getMessageState(message.message_id)
  }

  function sendMessage(content: string, receiverId?: string, files?: any[]) {
    if (!content.trim() && (!files || files.length === 0)) {
      console.log('[ChatStore] sendMessage skipped: empty content')
      return
    }

    // Generate messageId for optimistic update AND to share with extension
    const messageId = `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`
    
    const targetReceiver = receiverId || defaultAgentId.value
    console.log('[ChatStore] sendMessage:', { messageId, content, targetReceiver, filesCount: files?.length })

    // Optimistic update - add user message locally
    const messageData: any = { content }
    if (files && files.length > 0) {
      messageData.files = files
    }

    addMessage({
      message_id: messageId,
      message_type: 'user_message',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: 'user',
      receiver_id: targetReceiver,
      data: messageData,
    })

    // Send to extension host
    console.log('[ChatStore] posting sendMessage to extension')
    postMessage({
      type: 'sendMessage',
      payload: { content, receiverId: targetReceiver, files, messageId },
    })
  }

  function loadHistory(skip: number = 0, limit: number = 50) {
    if (skip === 0) {
      loading.value = true
    } else {
      loadingMore.value = true
    }

    postMessage({
      type: 'loadHistory',
      payload: { skip, limit },
    })
  }

  function loadMoreHistory() {
    if (loadingMore.value || !hasMoreHistory.value) return
    loadHistory(historySkip.value, 50)
  }

  function respondPermission(granted: boolean) {
    postMessage({
      type: 'respondPermission',
      payload: {
        granted,
        requestId: permissionDialog.value.requestId,
        receiverId: permissionDialog.value.senderId,
      },
    })
    permissionDialog.value.visible = false
  }

  function respondAgentQuery(answer: string) {
    postMessage({
      type: 'respondAgentQuery',
      payload: {
        answer,
        requestId: agentQueryDialog.value.requestId,
        receiverId: agentQueryDialog.value.senderId,
      },
    })
    agentQueryDialog.value.visible = false
  }

  function sendRedo() {
    postMessage({
      type: 'redo',
      payload: { receiverId: redoReceiverId.value },
    })
    showRedoButton.value = false
    redoReceiverId.value = undefined
  }

  function sendUndo(targetMessageId?: string, level: 'turn' | 'step' = 'step', receiverId?: string) {
    postMessage({
      type: 'undo',
      payload: { targetMessageId, level, receiverId },
    })
  }

  function sendAbort(receiverId?: string) {
    postMessage({
      type: 'abort',
      payload: { receiverId },
    })
  }

  return {
    sessionId,
    connected,
    messages,
    loading,
    loadingMore,
    hasMoreHistory,
    runnerInfo,
    inputText,
    permissionDialog,
    agentQueryDialog,
    showRedoButton,
    redoReceiverId,
    runnerAlive,
    defaultAgentId,
    agentNames,
    agents,
    agentStatuses,
    updateAgentStatus,
    getAgentStatus,
    getAgentRuntimeStatus,
    // Sidebar state
    showLeftSidebar,
    showRightSidebar,
    isMobile,
    toggleLeftSidebar,
    toggleRightSidebar,
    // Message state management
    messageStates,
    getMessageState,
    toggleToolParameters,
    toggleToolResult,
    toggleReasoning,
    // Init & actions
    init,
    sendMessage,
    loadHistory,
    loadMoreHistory,
    respondPermission,
    respondAgentQuery,
    sendRedo,
    sendUndo,
    sendAbort,
  }
})
