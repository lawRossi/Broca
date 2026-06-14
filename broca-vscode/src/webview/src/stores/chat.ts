import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { postMessage, onMessage, getInitialData } from '../api/vscode'
import type { Message, RunnerInfo } from '../types'

// ========== 简洁模式类型定义 ==========
interface ToolCallStat {
  toolName: string
  count: number
}

interface TodoItem {
  name: string
  status: 'pending' | 'in_progress' | 'completed'
}

interface TurnSummary {
  turnId: string
  sequenceNumber: number
  agentId: string
  agentName: string
  userMessage: string | null
  status: 'active' | 'completed' | 'error'
  currentTool: string | null
  currentFilePath: string | null
  currentTodoList: TodoItem[]
  totalDuration: number
  totalSteps: number
  toolCallStats: ToolCallStat[]
  finalResponse: string
  reasoningContent: string
  isActive: boolean
  startedAt: number
  createdAt: string
  /** 该 turn 最后一个非撤销消息的 message_id，用于 turn 级撤销定位 */
  lastMessageId: string | null
}

export const useChatStore = defineStore('chat', () => {
  const sessionId = ref(getInitialData()?.sessionId || '')
  const connected = ref(false)
  const messages = ref<Message[]>([])

  // Agent 消息可见性过滤
  const visibleAgentIds = ref<string[]>([])
  let _userModified = false

  function toggleAgentVisibility(agentId: string) {
    _userModified = true
    const idx = visibleAgentIds.value.indexOf(agentId)
    if (idx !== -1) {
      visibleAgentIds.value = visibleAgentIds.value.filter((id) => id !== agentId)
    } else {
      visibleAgentIds.value = [...visibleAgentIds.value, agentId]
    }
  }

  function setVisibleAgents(agentIds: string[]) {
    _userModified = true
    visibleAgentIds.value = agentIds
  }

  const filteredMessages = computed(() => {
    const visibleIds = visibleAgentIds.value
    if (visibleIds.length === 0) return messages.value

    // 判断是否处于筛选状态：visibleIds 不等于全部 Agent 数量
    const isAllSelected = agents.value.length > 0 && visibleIds.length >= agents.value.length

    return messages.value.filter((m) => {
      // 用户消息
      if (m.role === 'user') {
        // 优先按 receiver_id 过滤（用户通过 @mention 指定的接收者）
        if (m.receiver_id) {
          return visibleIds.includes(m.receiver_id)
        }
        // 无 receiver_id 时，按 agent_id 过滤（消息所属的 Agent）
        if (m.agent_id) {
          return visibleIds.includes(m.agent_id)
        }
        // 两者都没有 → 仅全部可见时才显示
        return isAllSelected
      }
      if (m.role === 'system' || m.message_type === 'system_message') return true
      if (m.sender_id && visibleIds.includes(m.sender_id)) return true
      if (m.agent_id && visibleIds.includes(m.agent_id)) return true
      return false
    })
  })

  const loading = ref(false)
  const loadingMore = ref(false)
  const hasMoreHistory = ref(true)
  const historySkip = ref(0)
  const historyTotal = ref(0)
  const runnerInfo = ref<RunnerInfo | null>(null)
  const runnerActionLoading = ref(false)
  const inputText = ref('')
  const defaultAgentId = ref<string | undefined>(undefined)
  const agentNames = ref<Record<string, string>>({})
  // Agent orchestration session flags
  const isAgentOrchestration = ref(getInitialData()?.category === 'agent-orchestration')
  const executionId = ref<string | undefined>(getInitialData()?.executionId)

  // ==================== 简洁模式状态 ====================
  const displayMode = ref<'detail' | 'concise'>('detail')
  const turnSummaries = ref<TurnSummary[]>([])
  const turnHistorySkip = ref(0)
  const hasMoreTurns = ref(true)
  const loadingMoreTurns = ref(false)
  const activeTurnIndex = ref(-1)
  const _turnLastResponseMsgId = ref(new Map<string, string>())
  const _turnContentMsgId = ref(new Map<string, string>())
  const _turnSeenToolCallIds = ref(new Set<string>())
  const durationTimer = ref<ReturnType<typeof setInterval> | null>(null)

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

  // ==================== 错误通知状态 ====================
  const errorToast = ref({
    visible: false,
    message: '',
    type: 'error' as 'error' | 'warning' | 'info',
  })
  let errorToastTimer: ReturnType<typeof setTimeout> | null = null

  function showError(message: string, type: 'error' | 'warning' | 'info' = 'error', duration: number = 5000) {
    errorToast.value = { visible: true, message, type }
    if (errorToastTimer) clearTimeout(errorToastTimer)
    errorToastTimer = setTimeout(() => {
      errorToast.value.visible = false
    }, duration)
  }

  function hideError() {
    errorToast.value.visible = false
    if (errorToastTimer) {
      clearTimeout(errorToastTimer)
      errorToastTimer = null
    }
  }

  const permissionDialog = ref({
    visible: false,
    requestId: '' as string | undefined,
    senderId: '' as string | undefined,
    message: '',
    requestType: 'general' as string,
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

  // ==================== 简洁模式计算属性 ====================
  const filteredTurnSummaries = computed(() => {
    return turnSummaries.value.filter(t => !(t.isActive && t.status === 'error'))
  })

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
          const agentList = (data.payload.agents || []).map((a: any) => ({
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
          agents.value = agentList
          // 用户未手动筛选过时，默认全部可见
          if (!_userModified) {
            visibleAgentIds.value = agentList.map((a: any) => a.agent_id)
          }
          // Initialize agent statuses to 'idle' for all known agents
          const initialStatuses: Record<string, AgentStatus> = {}
          for (const agent of agentList) {
            initialStatuses[agent.agent_id] = agent.status === 'running' ? 'running' : 'idle'
          }
          agentStatuses.value = initialStatuses
          // Build agent name map (for backward compatibility)
          const names: Record<string, string> = {}
          for (const agent of agentList) {
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
          runnerActionLoading.value = false
          break

        case 'runnerActionResult':
          runnerActionLoading.value = false
          break

        case 'turnsData':
          // loadTurnHistory 使用 Promise 方式处理，但如果外部收到 turnsData 也做兜底
          console.log('[ChatStore] turnsData received:', data.payload)
          break

        case 'error':
          console.error('Extension error:', data.payload.message)
          showError(data.payload.message || '操作失败', 'error')
          break
      }
    })

    // 加载简洁模式偏好，若为简洁模式则同时加载 turn 数据
    const savedMode = loadDisplayMode(sessionId.value)
    if (savedMode === 'concise' && sessionId.value) {
      loadTurnHistory(sessionId.value, false)
    }

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
        requestType: message.data?.request_type || 'general',
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

    // ===== Agent 运行状态更新 + 简洁模式 turn 更新：在 processMessage 之前处理 =====
    if (message.message_type === 'turn_start') {
      const targetAgentId = message.sender_id || message.agent_id || defaultAgentId.value
      updateAgentStatus(targetAgentId, 'running')
      // 简洁模式：创建新的 turn summary
      handleTurnStartMessage(message)
      return  // turn_start 不需要显示在消息列表中
    }

    if (message.message_type === 'turn_end') {
      const targetAgentId = message.sender_id || message.agent_id || defaultAgentId.value
      updateAgentStatus(targetAgentId, 'idle')
      // 简洁模式：标记 turn 完成
      handleTurnEndMessage(message)
      return  // turn_end 不需要显示在消息列表中
    }

    // 简洁模式：step_start / step_end 在 processMessage 过滤前更新 turn 摘���，然后提前返回
    if (message.message_type === 'step_start' || message.message_type === 'step_end') {
      updateTurnSummaryOnStepEvent(message)
      return  // 不显示在消息列表中
    }

    // agent_response 和 tool_call 也更新 Agent 状态为 running
    if (message.message_type === 'agent_response' || message.message_type === 'tool_call') {
      const targetAgentId = message.sender_id || message.agent_id || defaultAgentId.value
      updateAgentStatus(targetAgentId, 'running')
    }

    // 始终更新 turn 摘要（无论当前 displayMode），确保切换模式时数据已就绪
    if (
      message.message_type === 'agent_response' ||
      message.message_type === 'user_message' ||
      message.message_type === 'tool_call' ||
      message.message_type === 'reasoning_content'
    ) {
      updateTurnSummaryOnMessage(message)
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
      if (message.data?.result.code !== 0) {
        alert(message.data?.result.message || 'Error')
        return
      }
      if (message.data?.command === 'undo') {
        showRedoButton.value = true
        redoReceiverId.value = message.sender_id
        loadHistory(0, 50)
        // 简洁模式：重新加载 turn 历史，刷新被撤销的 turn
        if (sessionId.value) loadTurnHistory(sessionId.value, false)
        return
      } else if (message.data?.command === 'redo') {
        showRedoButton.value = false
        redoReceiverId.value = undefined
        loadHistory(0, 50)
        // 简洁模式：重新加载 turn 历史
        if (sessionId.value) loadTurnHistory(sessionId.value, false)
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

    // 用户消息按 message_id 去重：agent 开始处理时会重新广播用户消息
    if (message.message_type === 'user_message') {
      const existingUserMsg = messages.value.findIndex(
        m => m.message_type === 'user_message' && m.message_id === message.message_id
      )
      if (existingUserMsg !== -1) {
        // 更新 data（保留位置不变）
        messages.value[existingUserMsg] = {
          ...messages.value[existingUserMsg],
          data: { ...messages.value[existingUserMsg].data, ...message.data },
          timestamp: message.timestamp,
        }
        return
      }
    }

    messages.value.push(message)
    getMessageState(message.message_id)
  }

  function sendMessage(content: string, receiverId?: string, files?: any[]) {
    // Disable sending in orchestration sessions
    if (isAgentOrchestration.value) {
      console.log('[ChatStore] sendMessage blocked: orchestration session is read-only')
      return
    }
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

    const payload: any = { skip, limit }
    // If executionId is set, filter messages by this execution
    if (executionId.value) {
      payload.executionId = executionId.value
    }

    postMessage({
      type: 'loadHistory',
      payload,
    })
  }

  function loadMoreHistory() {
    if (loadingMore.value || !hasMoreHistory.value) return
    loadHistory(historySkip.value, 50)
  }

  function respondPermission(granted: boolean, sessionAction?: string) {
    postMessage({
      type: 'respondPermission',
      payload: {
        granted,
        session_action: sessionAction,
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
    if (isAgentOrchestration.value) return
    postMessage({
      type: 'redo',
      payload: { receiverId: redoReceiverId.value },
    })
    showRedoButton.value = false
    redoReceiverId.value = undefined
  }

  function sendUndo(targetMessageId?: string, level: 'turn' | 'step' = 'step', receiverId?: string) {
    if (isAgentOrchestration.value) return
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

  // ==================== 简洁模式方法 ====================

  function loadDisplayMode(sessionId: string): 'detail' | 'concise' {
    try {
      const saved = sessionStorage.getItem(`broca_display_mode_${sessionId}`)
      if (saved === 'detail' || saved === 'concise') {
        displayMode.value = saved
        return saved
      }
    } catch {
      // sessionStorage 可能在隐私模式下不可用
    }
    displayMode.value = 'detail'
    return 'detail'
  }

  function saveDisplayMode(sessionId: string, mode: 'detail' | 'concise') {
    try {
      sessionStorage.setItem(`broca_display_mode_${sessionId}`, mode)
    } catch {
      // sessionStorage 不可用时忽略
    }
  }

  function toggleDisplayMode() {
    const newMode = displayMode.value === 'detail' ? 'concise' : 'detail'
    displayMode.value = newMode
    saveDisplayMode(sessionId.value, newMode)

    if (newMode === 'concise') {
      // 切换到简洁模式：如有活跃 turn，启动计时器
      if (turnSummaries.value.some(t => t.isActive)) {
        startDurationTimer()
      }
      // 首次加载 turn 数据
      if (turnSummaries.value.length === 0) {
        loadTurnHistory(sessionId.value, false)
      }
    } else {
      // 切换到明细模式：停止计时器
      stopDurationTimer()
    }
  }

  async function loadTurnHistory(sessionId: string, isLoadMore: boolean) {
    if (isLoadMore) {
      if (loadingMoreTurns.value || !hasMoreTurns.value) return
      loadingMoreTurns.value = true
    }

    const skip = isLoadMore ? turnHistorySkip.value : 0
    const limit = 3

    // 使用 Promise 包装 postMessage 请求，等待 extension host 响应
    const response = await new Promise<any>((resolve, reject) => {
      const timeout = setTimeout(() => {
        cleanup()
        reject(new Error('fetchTurns timeout'))
      }, 15000)

      const handler = (data: any) => {
        if (data.type === 'turnsData' && data.payload) {
          cleanup()
          resolve(data.payload)
        } else if (data.type === 'error') {
          cleanup()
          reject(new Error(data.payload?.message || 'fetchTurns failed'))
        }
      }

      const cleanup = () => {
        clearTimeout(timeout)
        unsub()
      }

      // Register one-time handler
      const unsub = onMessage(handler)

      postMessage({
        type: 'fetchTurns',
        payload: { sessionId, skip, limit },
      })
    })

    try {
      const { turns, total, skip: responseSkip } = response

      const turnList: TurnSummary[] = (turns || []).map((t: any) => ({
        turnId: t.turn_id || '',
        sequenceNumber: t.sequence_number || 0,
        agentId: t.agent_id || '',
        agentName: t.agent_name || t.agent_id || '',
        userMessage: t.user_message || null,
        status: t.status === 'error' ? 'error' : t.status === 'active' ? 'active' : 'completed',
        currentTool: t.current_tool || null,
        currentFilePath: t.current_file_path || null,
        currentTodoList: (t.current_todo_list || []).map((item: any) => ({
          name: item.name || '',
          status: item.status || 'pending',
        })),
        totalDuration: t.total_duration || 0,
        totalSteps: t.total_steps || 0,
        toolCallStats: (t.tool_call_stats || []).map((stat: any) => ({
          toolName: stat.tool_name || '',
          count: stat.count || 0,
        })),
        finalResponse: t.final_response || '',
        reasoningContent: t.reasoning_content || '',
        isActive: t.is_active || false,
        startedAt: t.started_at ? new Date(t.started_at).getTime() : Date.now(),
        createdAt: t.created_at || new Date().toISOString(),
        lastMessageId: t.last_message_id || null,
      }))

      if (skip === 0) {
        // 初始加载时，保留当前活跃 turn（正在通过 socket 实时更新），避免覆盖
        const activeTurns = turnSummaries.value.filter(t => t.isActive)
        // 合并 API 数据和活跃 turn，API 数据中已有的 turnId 会被活跃版本替换
        const mergedTurns = [...turnList]
        const existingIds = new Set(mergedTurns.map(t => t.turnId))
        for (const active of activeTurns) {
          if (existingIds.has(active.turnId)) {
            // 替换 API 中的对应 turn 为活跃版本
            const idx = mergedTurns.findIndex(t => t.turnId === active.turnId)
            if (idx !== -1) mergedTurns[idx] = active
          } else {
            // API 中没有此活跃 turn（可能是最新的），追加到末尾
            mergedTurns.push(active)
          }
        }
        turnSummaries.value = mergedTurns
      } else {
        turnSummaries.value = [...turnList, ...turnSummaries.value]
      }

      turnHistorySkip.value = responseSkip + turnList.length
      hasMoreTurns.value = turnHistorySkip.value < (total || 0)

      // 降级检测：无 turn 但有消息时自动切回 detail
      if (turnList.length === 0 && messages.value.length > 0) {
        displayMode.value = 'detail'
      }
    } catch (err: any) {
      showError(err.message || '加载 turn 历史失败', 'error')
    } finally {
      loadingMoreTurns.value = false
    }
  }

  function startDurationTimer() {
    stopDurationTimer()
    durationTimer.value = setInterval(() => {
      const activeTurn = turnSummaries.value.find(t => t.isActive)
      if (activeTurn) {
        activeTurn.totalDuration = Math.floor((Date.now() - activeTurn.startedAt) / 1000)
      }
    }, 500)
  }

  function stopDurationTimer() {
    if (durationTimer.value !== null) {
      clearInterval(durationTimer.value)
      durationTimer.value = null
    }
  }

  function resetTurnData() {
    displayMode.value = 'detail'
    turnSummaries.value = []
    turnHistorySkip.value = 0
    hasMoreTurns.value = true
    loadingMoreTurns.value = false
    activeTurnIndex.value = -1
    _turnLastResponseMsgId.value = new Map()
    _turnContentMsgId.value = new Map()
    _turnSeenToolCallIds.value = new Set()
    stopDurationTimer()
  }

  /**
   * 查找消息所属的 turnId
   * 
   * 与 web 版一致：优先用消息自带的 turn_id，但需要验证该 turn 确实存在；
   * 若不存在则回退到活跃 turn（解决 turn_start 可能无 turn_id 导致 ID 不一致的问题）。
   */
  function _turnIdForMessage(message: Message): string | null {
    // 1. 尝试消息自带的 turn_id，但需验证该 turn 确实存在
    const msgTurnId = message.turn_id || message.data?.turn_id
    if (msgTurnId && turnSummaries.value.some(t => t.turnId === msgTurnId)) {
      return msgTurnId
    }
    // 2. 回退到活跃 turn（turn_start 可能无 turn_id 时，后续消息用此兜底）
    const activeTurn = turnSummaries.value.find(t => t.isActive)
    if (activeTurn) return activeTurn.turnId
    // 3. 仍无匹配，尝试通过 timestamp 找最近的 completed turn
    if (!message.timestamp) return null
    const msgTime = new Date(message.timestamp).getTime()
    const recentTurn = [...turnSummaries.value]
      .reverse()
      .find(t => !t.isActive && Math.abs(new Date(t.createdAt).getTime() - msgTime) < 60000)
    return recentTurn?.turnId || null
  }

  function handleTurnStartMessage(message: Message) {
    const turnId = message.turn_id || message.data?.turn_id || message.message_id || `turn_${Date.now()}`
    const agentId = message.sender_id || message.agent_id || defaultAgentId.value || ''

    // 幂等检查：防止重复创建
    if (turnSummaries.value.some(t => t.turnId === turnId)) return

    const summary: TurnSummary = {
      turnId,
      sequenceNumber: turnSummaries.value.length + 1,
      agentId,
      agentName: agentNames.value[agentId] || agentId,
      userMessage: null,
      status: 'active',
      currentTool: null,
      currentFilePath: null,
      currentTodoList: [],
      totalDuration: 0,
      totalSteps: 0,
      toolCallStats: [],
      finalResponse: '',
      reasoningContent: '',
      isActive: true,
      startedAt: Date.now(),
      createdAt: message.timestamp || new Date().toISOString(),
      lastMessageId: null,
    }

    turnSummaries.value.push(summary)
    activeTurnIndex.value = turnSummaries.value.length - 1
    startDurationTimer()
  }

  function handleTurnEndMessage(message: Message) {
    const turnId = message.turn_id || ''
    const turn = turnSummaries.value.find(t => t.turnId === turnId) ||
                 turnSummaries.value.find(t => t.isActive)

    if (!turn) return

    turn.isActive = false
    turn.status = message.data?.error ? 'error' : 'completed'
    stopDurationTimer()

    // 如果有 lastMessageId，从 _turnLastResponseMsgId 更新
    if (turn.lastMessageId) {
      _turnLastResponseMsgId.value.set(turn.turnId, turn.lastMessageId)
    }

    activeTurnIndex.value = -1
  }

  function updateTurnSummaryOnStepEvent(message: Message) {
    const turnId = _turnIdForMessage(message)
    if (!turnId) return
    const turn = turnSummaries.value.find(t => t.turnId === turnId)
    if (!turn) return

    if (message.message_type === 'step_start') {
      turn.totalSteps++
    } else if (message.message_type === 'step_end') {
      // 步骤结束时清除当前工具
      turn.currentTool = null
    }
  }

  function updateTurnSummaryOnMessage(message: Message) {
    const turnId = _turnIdForMessage(message)
    if (!turnId) return
    const turn = turnSummaries.value.find(t => t.turnId === turnId)
    if (!turn) return

    switch (message.message_type) {
      case 'user_message':
        if (!turn.userMessage) {
          // 优先使用 raw_input（与明细模式 ChatMessageItem 一致）
          if (message.data?.raw_input !== undefined) {
            turn.userMessage = String(message.data.raw_input)
          } else {
            // 后端回显的 user_message 可能 JSON 包裹，与 web 版一致处理
            const raw = message.data?.content
            if (raw) {
              try {
                const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
                turn.userMessage = parsed?.content || String(parsed)
              } catch {
                turn.userMessage = String(raw)
              }
            }
          }
        }
        turn.lastMessageId = message.message_id
        break

      case 'tool_call': {
        const toolName = message.data?.tool_name
        if (!toolName) break

        // 更新状态（与 web 版一致）
        turn.status = 'calling_tool'

        // 只在首次设置 currentTool，同一 step 内后续 tool_call 不覆盖
        if (!turn.currentTool) {
          turn.currentTool = toolName
        }

        // 更新工具调用统计（与 web 版一致处理）
        const existing = turn.toolCallStats.find(s => s.toolName === toolName)
        if (existing) {
          existing.count++
        } else {
          turn.toolCallStats.push({ toolName, count: 1 })
        }

        // 提取文件路径（read_file/edit_file/write_file）
        if (['read_file', 'edit_file', 'write_file'].includes(toolName)) {
          const args = message.data?.arguments
          if (args) {
            try {
              const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
              turn.currentFilePath = parsedArgs.path || null
            } catch {}
          }
        }

        // 提取 TODO 列表（todo_management）
        if (toolName === 'todo_management') {
          const args = message.data?.arguments
          if (args) {
            try {
              const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
              if (parsedArgs.todos) {
                turn.currentTodoList = parsedArgs.todos
              }
            } catch {}
          }
        }

        turn.lastMessageId = message.message_id
        break
      }

      case 'agent_response': {
        // 更新状态（与 web 版一致）
        turn.status = 'thinking'

        // 累加最终回复（与 web 版一致处理 streaming chunks）：
        // 同一 message_id 的 streaming chunk 连续拼接，
        // 不同 message_id（不同 LLM 调用）之间加空行分隔。
        const content = message.data?.content
        if (content) {
          try {
            const parsed = JSON.parse(content)
            if (parsed.content || parsed.reasoning_content) {
              const lastMsgId = _turnLastResponseMsgId.value.get(turn.turnId)
              const isNewResponse = lastMsgId !== message.message_id

              // finalResponse：累加拼接
              if (parsed.content) {
                const prevContentMsgId = _turnContentMsgId.value.get(turn.turnId)
                if (prevContentMsgId !== message.message_id && turn.finalResponse.length > 0) {
                  turn.finalResponse += '\n\n'
                }
                turn.finalResponse += parsed.content
                _turnContentMsgId.value.set(turn.turnId, message.message_id)
              }

              // reasoningContent：同一 message_id 内 chunks 累加；
              // 一旦收到回复内容（content），清空 reasoningContent。
              if (parsed.reasoning_content) {
                if (isNewResponse) {
                  turn.reasoningContent = parsed.reasoning_content
                } else {
                  turn.reasoningContent += parsed.reasoning_content
                }
              }
              if (parsed.content && turn.reasoningContent.length > 0) {
                turn.reasoningContent = ''
              }

              _turnLastResponseMsgId.value.set(turn.turnId, message.message_id)
            }
          } catch {
            // 非 JSON 格式，直接拼接
            turn.finalResponse += content
          }
        }
        turn.lastMessageId = message.message_id
        break
      }

      case 'reasoning_content':
        if (message.data?.content) {
          turn.reasoningContent += message.data.content
        }
        turn.lastMessageId = message.message_id
        break
    }
  }

  return {
    sessionId,
    connected,
    messages,
    filteredMessages,
    visibleAgentIds,
    toggleAgentVisibility,
    setVisibleAgents,
    loading,
    loadingMore,
    hasMoreHistory,
    runnerInfo,
    runnerActionLoading,
    inputText,
    // Error toast
    errorToast,
    showError,
    hideError,
    // Dialogs
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
    // Agent orchestration flags
    isAgentOrchestration,
    executionId,
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
    // ==================== 简洁模式状态 ====================
    displayMode,
    turnSummaries,
    filteredTurnSummaries,
    turnHistorySkip,
    hasMoreTurns,
    loadingMoreTurns,
    activeTurnIndex,
    // ==================== 简洁模式方法 ====================
    loadDisplayMode,
    saveDisplayMode,
    toggleDisplayMode,
    loadTurnHistory,
    startDurationTimer,
    stopDurationTimer,
    resetTurnData,
    handleTurnStartMessage,
    handleTurnEndMessage,
    updateTurnSummaryOnStepEvent,
    updateTurnSummaryOnMessage,
  }
})
