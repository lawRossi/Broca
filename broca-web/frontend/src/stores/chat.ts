import { defineStore } from 'pinia'
import { ref, computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useAgentStore, useSocketStore } from '@/stores'
import { type Message } from '@/api/brocaSocket'
import { sessionApi, type RunnerInfo } from '@/api/session'

// ========== 简洁模式类型定义 ==========
interface ToolCallStat {
  toolName: string
  count: number
}

interface TodoItem {
  name: string
  status: 'pending' | 'in_progress' | 'completed'
}

interface ChangedFiles {
  totalAdded: number
  totalDeleted: number
  totalModified: number
  filesAdded: string[]
  filesDeleted: string[]
  filesModified: string[]
}

interface TurnSummary {
  turnId: string
  sequenceNumber: number
  agentId: string
  agentName: string
  userMessage: string | null
  status: 'active' | 'thinking' | 'calling_tool' | 'completed' | 'error'
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
  /** 文件变更摘要 */
  changedFiles: ChangedFiles | null
}

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
  const executionId = ref<string | undefined>(undefined)
  const loadingMore = ref(false)
  const hasMoreHistory = ref(true)
  const historySkip = ref(0)
  const historyTotal = ref(0)
  const messagesContainer = ref<HTMLElement>()

  // 撤销/重做相关状态
  const showRedoButton = ref(false)
  const redoReceiverId = ref<string | undefined>()
  // 编排会话标记（禁用撤销/重做）
  const isAgentOrchestration = ref(false)

  // ========== 简洁模式状态 ==========
  /** 从 localStorage 读取会话显示模式 */
  const loadDisplayMode = (sid: string): 'detail' | 'concise' => {
    try {
      const saved = localStorage.getItem(`broca_display_mode_${sid}`)
      if (saved === 'concise' || saved === 'detail') return saved
    } catch { /* localStorage 不可用时忽略 */ }
    return 'concise'
  }
  /** 将会话显示模式持久化到 localStorage */
  const saveDisplayMode = (sid: string, mode: 'detail' | 'concise') => {
    try {
      localStorage.setItem(`broca_display_mode_${sid}`, mode)
    } catch { /* 忽略 */ }
  }
  const displayMode = ref<'detail' | 'concise'>('concise')
  const turnSummaries = ref<TurnSummary[]>([])
  const turnHistorySkip = ref(0)
  const hasMoreTurns = ref(true)
  const loadingMoreTurns = ref(false)
  const activeTurnIndex = ref<number>(-1)
  /** 模式切换时的滚动位置百分比，由 ChatMessageList 设置/消费 */
  const pendingScrollPercentage = ref<number | null>(null)
  let durationTimer: ReturnType<typeof setInterval> | null = null

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
      // Runner 轮询失败属于后台行为，静默处理即可
      console.debug('获取Runner状态失败:', error)
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
      // 立刻刷新状态
      await fetchRunnerStatus()
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
    requestType: 'general' as string,
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

  // 根据 Agent 可见性过滤消息
  const filteredMessages = computed(() => {
    const visibleIds = agentStore.visibleAgentIds
    if (visibleIds.length === 0) return messages.value

    // 判断是否处于筛选状态：visibleIds 不等于全部 Agent 数量
    const totalAgents = agentStore.agents.length
    const isAllSelected = totalAgents > 0 && visibleIds.length >= totalAgents

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
      // 系统消息始终显示
      if (m.role === 'system' || m.message_type === 'system_message') return true
      // 根据 sender_id 或 agent_id 过滤
      if (m.sender_id && visibleIds.includes(m.sender_id)) return true
      if (m.agent_id && visibleIds.includes(m.agent_id)) return true
      return false
    })
  })

  // 根据 Agent 可见性过滤 turn 摘要（简洁模式）
  const filteredTurnSummaries = computed(() => {
    const summaries = turnSummaries.value
    const visibleIds = agentStore.visibleAgentIds
    if (visibleIds.length === 0) return summaries
    return summaries.filter(t => visibleIds.includes(t.agentId))
  })

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
  const processMessage = (msg: any, skipStepEvents: boolean = false): Message | null => {
    const message = msg as Message

    // step_start/step_end: 路由到 TurnSummary 更新，不加入 messages[]
    // 加载历史消息时跳过，避免重复统计（历史 step 数据已由后端聚合）
    if (message.message_type === 'step_start') {
      if (!skipStepEvents) {
        updateTurnSummaryOnStepEvent(message)
      }
      return null
    }
    if (message.message_type === 'step_end') {
      if (!skipStepEvents) {
        updateTurnSummaryOnStepEvent(message)
      }
      return null
    }

    // turn_start/turn_end: 由 onMessage 回调中的 handleTurnStart/handleTurnEnd 处理
    if (message.message_type === 'turn_start' || message.message_type === 'turn_end') {
      return null
    }

    // 过滤不需要显示的消息类型
    const filteredTypes = [
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

  /**
   * 将 ISO 字符串解析为 UTC 时间戳（ms）。
   * 处理服务端返回的无时区 ISO 字符串（如 "2024-01-15T10:30:00.123456"），
   * 将其视为 UTC 时间而非本地时间。
   */
  const parseISODate = (iso: string | null | undefined): number | null => {
    if (!iso) return null
    // 如果字符串不包含时区信息（不以 Z 结尾，不包含 +/-），追加 Z 标记为 UTC
    const normalized = /[Z+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z'
    const ms = new Date(normalized).getTime()
    return isNaN(ms) ? null : ms
  }

  // ========== 简洁模式：TurnSummary 更新方法 ==========

  /** 记录每个 turn 最后一次 agent_response 的 message_id，用于在 finalResponse 中插入分隔符 */
  const _turnLastResponseMsgId = new Map<string, string>()
  /** 记录每个 turn 已追加过 content 的 message_id（与 reasoning 分开追踪，避免 reasoning-only chunk 消耗 isNewResponse） */
  const _turnContentMsgId = new Map<string, string>()
  /** 记录每个 turn 已统计过的 tool_call_id，去重计数 */
  const _turnSeenToolCallIds = new Map<string, Set<string>>()
  const updateTurnSummaryOnStepEvent = (message: Message) => {
    const turnId = message.turn_id
    if (!turnId) return

    const idx = turnSummaries.value.findIndex(t => t.turnId === turnId)
    if (idx === -1) return

    if (message.message_type === 'step_start') {
      turnSummaries.value[idx].totalSteps++
    } else if (message.message_type === 'step_end') {
      // 步骤结束时清除当前工具，避免 tool_call 结束后到 turn_end 前持续显示"当前调用"
      turnSummaries.value[idx].currentTool = null
    }
  }

  const updateTurnSummaryOnMessage = (message: Message) => {
    const turnId = message.turn_id || message.data?.turn_id
    if (!turnId) return

    const idx = turnSummaries.value.findIndex(t => t.turnId === turnId)
    if (idx === -1) return

    const turn = turnSummaries.value[idx]

    if (message.message_type === 'user_message') {
      if (!turn.userMessage) {
        // 优先使用 raw_input（与明细模式 ChatMessageItem 一致）
        if (message.data?.raw_input !== undefined) {
          turn.userMessage = String(message.data.raw_input)
        } else {
          // data.content 是 json.dumps({"content": "用户消息", ...})
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
      // 记录最后一条消息 ID（用于撤销定位）
      _turnLastResponseMsgId.set(turnId, message.message_id)
    } else if (message.message_type === 'tool_call') {
      const toolName = message.data?.tool_name
      if (!toolName) return

      // 只在首次设置 currentTool，同一 step 内后续 tool_call 不覆盖
      if (!turn.currentTool) {
        turn.currentTool = toolName
      }

      // 更新工具调用统计（去重：同一 tool_call_id 会发送 preview→actual→result 三次）
      const toolCallId = message.data?.tool_call_id
      let isFirstSeen = true
      if (toolCallId) {
        const seenIds = _turnSeenToolCallIds.get(turnId) || new Set()
        if (seenIds.has(toolCallId)) {
          isFirstSeen = false
        } else {
          seenIds.add(toolCallId)
          _turnSeenToolCallIds.set(turnId, seenIds)
        }
      }
      if (isFirstSeen) {
        const existingStat = turn.toolCallStats.find(s => s.toolName === toolName)
        if (existingStat) {
          existingStat.count++
        } else {
          turn.toolCallStats.push({ toolName, count: 1 })
        }
      }

      // 提取文件路径（read_file/edit_file/write_file）
      if (['read_file', 'edit_file', 'write_file'].includes(toolName)) {
        const args = message.data?.arguments
        if (args) {
          const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
          turn.currentFilePath = parsedArgs.path || null
        }
      }

      // 提取 TODO 列表（todo_management）
      if (toolName === 'todo_management') {
        const args = message.data?.arguments
        if (args) {
          const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
          if (parsedArgs.todos) {
            turn.currentTodoList = parsedArgs.todos
          }
        }
      }

      turn.status = 'calling_tool'
      // 记录最后一条消息 ID（用于撤销定位）
      _turnLastResponseMsgId.set(turnId, message.message_id)
    } else if (message.message_type === 'agent_response') {
      // 累加最终回复；同一 message_id 的 streaming chunk 连续拼接，
      // 不同 message_id（不同 LLM 调用）之间加空行分隔。
      const content = message.data?.content
      if (content) {
        try {
          const parsed = JSON.parse(content)
          if (parsed.content || parsed.reasoning_content) {
            const lastMsgId = _turnLastResponseMsgId.get(turnId)
            const isNewResponse = lastMsgId !== message.message_id

            // finalResponse：同一 message_id 的 streaming chunks 连续拼接，
            // 不同 message_id（不同 LLM 调用）之间加空行分隔。
            // 注意：isNewResponse 可能在 reasoning-only chunk 时已被消耗，
            // 因此用独立的 _turnContentMsgId 判断是否已对当前 message_id 追加过 content。
            if (parsed.content) {
              const prevContentMsgId = _turnContentMsgId.get(turnId)
              if (prevContentMsgId !== message.message_id && turn.finalResponse.length > 0) {
                turn.finalResponse += '\n\n'
              }
              turn.finalResponse += parsed.content
              _turnContentMsgId.set(turnId, message.message_id)
            }

            // reasoningContent：同一 message_id 内 chunks 累加；
            // 一旦收到回复内容（content），表示模型已从思考切换到回复阶段，清空 reasoningContent。
            // 场景：streaming 前几块只有 reasoning_content，后几块切换到 content，
            // 此时 isNewResponse=false（同 message_id），但需要清空 reasoningContent。
            if (parsed.reasoning_content) {
              if (isNewResponse) {
                turn.reasoningContent = parsed.reasoning_content  // 新消息，重新开始
              } else {
                turn.reasoningContent += parsed.reasoning_content  // 同消息，累加
              }
            }
            if (parsed.content && turn.reasoningContent.length > 0) {
              // 收到回复内容 → 思考阶段已结束，清空 reasoningContent
              turn.reasoningContent = ''
            }

            _turnLastResponseMsgId.set(turnId, message.message_id)
          }
        } catch {
          turn.finalResponse += content
        }
      }
      turn.status = 'thinking'
    }
  }

  // 处理 turn_start 消息（创建 TurnSummary）
  const handleTurnStart = (message: Message) => {
    const turnId = message.data?.turn_id || message.turn_id
    if (!turnId) return

    // 检查是否已存在（避免重复）
    if (turnSummaries.value.some(t => t.turnId === turnId)) return

    const targetAgentId = message.sender_id || agentStore.currentAgentId
    const agent = agentStore.agents.find(a => a.agent_id === targetAgentId)
    const agentName = agent?.name || targetAgentId

    const newSummary: TurnSummary = {
      turnId,
      sequenceNumber: Math.max(0, ...turnSummaries.value.map(t => t.sequenceNumber)) + 1,
      agentId: targetAgentId,
      agentName,
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
      isReverted: false,
      startedAt: Date.now(),
      createdAt: new Date().toISOString(),
      lastMessageId: null,
      changedFiles: null,
    }

    turnSummaries.value.push(newSummary)
    activeTurnIndex.value = turnSummaries.value.length - 1
    startDurationTimer()
  }

  // 处理 turn_end 消息（终结 TurnSummary）
  const handleTurnEnd = (message: Message) => {
    const turnId = message.turn_id || message.data?.turn_id
    if (!turnId) return

    const idx = turnSummaries.value.findIndex(t => t.turnId === turnId)
    if (idx === -1) return

    const turn = turnSummaries.value[idx]
    turn.isActive = false
    turn.status = message.data?.status === 'error' || message.data?.status === 'aborted' ? 'error' : 'completed'
    turn.totalDuration = (Date.now() - turn.startedAt) / 1000

    if (activeTurnIndex.value === idx) {
      activeTurnIndex.value = -1
      stopDurationTimer()
    }
    // 保存 turn_end 消息 ID 用于撤销定位（始终安全，后端可能已删除最后响应消息）
    turn.lastMessageId = message.message_id
    // 提取文件变更信息
    if (message.data?.changed_files) {
      const cf = message.data.changed_files
      turn.changedFiles = {
        totalAdded: cf.total_added || 0,
        totalDeleted: cf.total_deleted || 0,
        totalModified: cf.total_modified || 0,
        filesAdded: cf.files_added || [],
        filesDeleted: cf.files_deleted || [],
        filesModified: cf.files_modified || [],
      }
    }
    _turnLastResponseMsgId.delete(turnId)
    _turnContentMsgId.delete(turnId)
    _turnSeenToolCallIds.delete(turnId)
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
    } else if (message.message_type === 'user_message') {
      // 乐观更新后，服务端会广播带 turn_id 的同一消息。按 message_id 合并避免重复。
      const existingIndex = messages.value.findIndex(
        (m) => m.message_type === 'user_message' && m.message_id === message.message_id
      )
      if (existingIndex !== -1) {
        const existing = messages.value[existingIndex]
        if (existing) {
          // 合并 data（保留乐观更新的字段，补充服务端回传的字段）
          existing.data = { ...existing.data, ...message.data }
          if (message.turn_id) existing.turn_id = message.turn_id
          if (message.agent_id) existing.agent_id = message.agent_id
          if (message.timestamp) existing.timestamp = message.timestamp
          return existing
        }
      }
      // 没有乐观更新记录（如其他客户端发送的消息），直接添加
      messages.value.push(message)
      if (!messageStates.value.has(message.message_id)) {
        messageStates.value.set(message.message_id, {
          showParameters: false,
          showResult: false,
          showReasoning: false,
        })
      }
      return message
    } else {
      // 通用去重：按 message_id 检查是否已存在
      const existingIndex = messages.value.findIndex(
        (m) => m.message_id === message.message_id
      )
      if (existingIndex !== -1) {
        const existing = messages.value[existingIndex]
        if (existing) {
          existing.data = { ...existing.data, ...message.data }
          if (message.timestamp) existing.timestamp = message.timestamp
          return existing
        }
      }
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

  const loadHistory = async (sessionId: string, isLoadMore: boolean = false, filterExecutionId?: string) => {
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

      const response = await sessionApi.getSessionMessages(sessionId, skip, limit, filterExecutionId)
      historyTotal.value = response.total

      if (response.messages) {
        const allMessages = response.messages
        const historyMessages: Message[] = []

        allMessages.forEach((msg: any) => {
          // 历史消息中的 step_start/step_end 已由后端聚合为 totalSteps，无需前端再次统计
          const processed = processMessage(msg, true)
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
      // 首次加载失败时给用户可见提示
      if (!isLoadMore) {
        const { ElMessage } = await import('element-plus')
        ElMessage.error('加载消息历史失败，请刷新页面重试')
      }
    } finally {
      loading.value = false
      loadingMore.value = false
    }
  }

  // ========== 简洁模式方法 ==========

  const loadTurnHistory = async (
    sessionId: string,
    isLoadMore: boolean = false,
    filterExecutionId?: string,
    reset: boolean = false
  ) => {
    if (isLoadMore) {
      if (loadingMoreTurns.value || !hasMoreTurns.value) return
      loadingMoreTurns.value = true
    } else if (reset) {
      // reset=true: 清空现有数据，适用于 undo/redo 等数据已根本改变的场景
      turnSummaries.value = []
      turnHistorySkip.value = 0
      hasMoreTurns.value = true
      activeTurnIndex.value = -1
      _turnLastResponseMsgId.clear()
      _turnSeenToolCallIds.clear()
    } else {
      // 注意：不清空 turnSummaries！因为在调用 loadTurnHistory 之前，
      // socket 事件（handleTurnStart/handleTurnEnd）可能已通过 onMessage 向
      // turnSummaries 添加了活跃的 turn（例如 autoConnectAndSubscribe 中
      // doSubscribe 之后、loadTurnHistory 之前的间隙，或 toggleDisplayMode
      // 切换过程中 socket 仍在处理事件）。清空会导致这些 turn 永久丢失。
      // merge 逻辑会正确合并 API 数据和现有 turn（去重）。
      turnHistorySkip.value = 0
      hasMoreTurns.value = true
      activeTurnIndex.value = -1
      _turnLastResponseMsgId.clear()
      _turnSeenToolCallIds.clear()
    }

    try {
      const response = await sessionApi.getSessionTurns(
        sessionId,
        turnHistorySkip.value,
        3,
        filterExecutionId
      )

      const newSummaries: TurnSummary[] = response.turns
        .filter(t => !t.is_reverted)  // 前端过滤已撤销的 turn
        .map(t => ({
          turnId: t.turn_id,
          sequenceNumber: t.sequence_number,
          agentId: t.agent_id,
          agentName: t.agent_name || 'Unknown',
          userMessage: t.user_message,
          status: (t.status === 'error' ? 'error' : 'completed') as const,
          currentTool: null,
          currentFilePath: t.current_file_path,
          currentTodoList: (t.current_todo_list || []) as TodoItem[],
          totalDuration: t.duration_seconds || 0,
          totalSteps: t.total_steps || 0,
          toolCallStats: (t.tool_call_stats || []).map(s => ({
            toolName: s.tool_name,
            count: s.count,
          })),
          finalResponse: t.final_response || '',
          reasoningContent: '',
          isActive: !t.ended_at,
          startedAt: parseISODate(t.started_at) ?? Date.now(),
          createdAt: t.created_at || '',
          lastMessageId: t.last_message_id || null,
          changedFiles: t.changed_files ? {
            totalAdded: t.changed_files.total_added || 0,
            totalDeleted: t.changed_files.total_deleted || 0,
            totalModified: t.changed_files.total_modified || 0,
            filesAdded: t.changed_files.files_added || [],
            filesDeleted: t.changed_files.files_deleted || [],
            filesModified: t.changed_files.files_modified || [],
          } : null,
        }))

      if (isLoadMore) {
        turnSummaries.value = [...newSummaries, ...turnSummaries.value]
      } else {
        // 合并 API 返回的 turn 和当前存在的活跃 turn（去重，活跃 turn 放最后）
        // 注意：不能只使用 API 调用前保存的 activeTurns，因为在 await 期间，
        // socket 事件（handleTurnStart）可能向 turnSummaries 添加了新的活跃 turn。
        // 如果只合并 activeTurns，这些中途添加的 turn 会被下面的赋值语句覆盖丢失。
        const seenIds = new Set(newSummaries.map(t => t.turnId))
        // 捕获当前 turnSummaries 中所有未被 API 数据覆盖的 turn
        // 包含：(1) API 调用前就活跃的 turn (2) API 调用期间 socket 新添加的 turn
        const currentLive = turnSummaries.value.filter(t => !seenIds.has(t.turnId))
        turnSummaries.value = [...newSummaries, ...currentLive]
      }

      // 检测活跃 turn
      if (!isLoadMore) {
        const activeIdx = turnSummaries.value.findIndex(s => s.isActive)
        if (activeIdx >= 0) {
          activeTurnIndex.value = activeIdx
          // 如果合并后有活跃 turn，确保计时器在运行
          startDurationTimer()
        }

        // 降级检测：无 turn 数据但有消息 → 自动切回明细模式
        if (turnSummaries.value.length === 0 && messages.value.length > 0) {
          displayMode.value = 'detail'
          console.warn('ChatConciseMode: 该会话暂无轮次数据，已自动降级到明细模式')
        }
      }

      turnHistorySkip.value += response.turns.length
      hasMoreTurns.value = turnHistorySkip.value < response.total
    } finally {
      loadingMoreTurns.value = false
    }
  }

  const startDurationTimer = () => {
    stopDurationTimer()
    durationTimer = setInterval(() => {
      if (activeTurnIndex.value >= 0 && activeTurnIndex.value < turnSummaries.value.length) {
        const turn = turnSummaries.value[activeTurnIndex.value]
        if (turn.isActive) {
          turn.totalDuration = (Date.now() - turn.startedAt) / 1000
        }
      }
    }, 500)
  }

  const stopDurationTimer = () => {
    if (durationTimer) {
      clearInterval(durationTimer)
      durationTimer = null
    }
  }

  /** 防止 toggleDisplayMode 并发调用的锁 */
  let _togglingDisplayMode = false

  const toggleDisplayMode = async () => {
    // 并发防护：如果已有切换操作在进行中，忽略本次调用
    if (_togglingDisplayMode) {
      console.debug('toggleDisplayMode: 已有切换操作进行中，忽略')
      return
    }
    _togglingDisplayMode = true
    try {
      const newMode = displayMode.value === 'detail' ? 'concise' : 'detail'
      displayMode.value = newMode
      saveDisplayMode(sessionId.value, newMode)

      if (newMode === 'concise' && turnSummaries.value.length === 0) {
        await loadTurnHistory(sessionId.value, false, executionId.value)
        // loadTurnHistory 内部已做降级检测，如果降级则 displayMode 已切回 'detail'
        if (displayMode.value === 'detail') return
        startDurationTimer()
      } else if (newMode === 'concise') {
        startDurationTimer()
      } else if (newMode === 'detail') {
        stopDurationTimer()
        // 只在没有任何消息时加载历史，避免与 socket 实时消息重复
        if (messages.value.length === 0 && !loading.value) {
          await loadHistory(sessionId.value, false, executionId.value)
        }
      }
    } finally {
      _togglingDisplayMode = false
    }
  }

  // 保存 socket 处理器注销函数，在 cleanup 时统一清理
  const _cleanupHandlers: (() => void)[] = []

  // 保存断开前的 agent 状态，用于重连时恢复（避免 running → disconnected → idle 的闪烁）
  let _preDisconnectStatuses = new Map<string, string>()

  const doConnect = async () => {
    socketStore.onConnect = () => {
      if (_preDisconnectStatuses.size > 0) {
        // === 重连场景：恢复断开前的 agent 状态 ===
        // 避免 onDisconnect 设置的 'disconnected' 覆盖正在运行的 agent 状态
        agentStore.agents = agentStore.agents.map((agent) => {
          const savedStatus = _preDisconnectStatuses.get(agent.agent_id)
          return {
            ...agent,
            status: savedStatus || 'idle',
          }
        })
        _preDisconnectStatuses.clear()
      } else {
        // === 首次连接场景：将数据库中读到的 'disconnected' 转为 'idle' ===
        agentStore.agents = agentStore.agents.map((agent) => ({
          ...agent,
          status: agent.status === 'disconnected' ? 'idle' : agent.status,
        }))
      }
    }
    socketStore.onDisconnect = () => {
      // 断开前保存当前 agent 状态，用于重连时恢复
      _preDisconnectStatuses.clear()
      agentStore.agents.forEach((agent) => {
        _preDisconnectStatuses.set(agent.agent_id, agent.status)
      })
      agentStore.agents = agentStore.agents.map((agent) => ({
        ...agent,
        status: 'disconnected',
      }))
      console.log('Disconnected from server')
    }
    const unsubMessage = socketStore.onMessage('chat', (m: Message) => {
      // 编排会话跳过撤销/重做处理
      if (isAgentOrchestration.value) {
        addMessage(m)
        if (m.message_type === 'turn_start') {
          handleTurnStart(m)
        } else if (m.message_type === 'turn_end') {
          handleTurnEnd(m)
        } else if (m.message_type === 'tool_call' || m.message_type === 'agent_response' || m.message_type === 'user_message') {
          updateTurnSummaryOnMessage(m)
        }
        return
      }

      // 如果是撤销或重做的结果，显示提示并重新加载消息
      if (m.message_type === 'command_result' && (m.data?.command === 'undo' || m.data?.command === 'redo')) {
        const result = m.data?.result
        if (result.code == 0) {
          if (m.data?.command === 'undo') {
            // 撤销成功后，显示重做按钮
            showRedoButton.value = true
            redoReceiverId.value = m.sender_id
            loadHistory(sessionId.value, false, executionId.value)
            loadTurnHistory(sessionId.value, false, executionId.value, true) // reset=true: 数据已改变
          } else {
            // 重做成功后，隐藏重做按钮
            showRedoButton.value = false
            redoReceiverId.value = undefined
            loadHistory(sessionId.value, false, executionId.value)
            loadTurnHistory(sessionId.value, false, executionId.value, true) // reset=true: 数据已改变
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

      // turn_start/turn_end: 在 message 事件中处理（服务器只发 message 事件，不发单独的 turn_start/turn_end 事件）
      if (m.message_type === 'turn_start') {
        const targetAgentId = m.sender_id || agentStore.currentAgentId
        agentStore.updateAgentStatus(targetAgentId, 'running')
        handleTurnStart(m)
      } else if (m.message_type === 'turn_end') {
        const targetAgentId = m.sender_id || agentStore.currentAgentId
        agentStore.updateAgentStatus(targetAgentId, 'idle')
        handleTurnEnd(m)
      }

      // tool_call、agent_response 和 user_message 同时更新 TurnSummary
      if (m.message_type === 'tool_call' || m.message_type === 'agent_response' || m.message_type === 'user_message') {
        updateTurnSummaryOnMessage(m)
      }
    })
    // turn_start/turn_end 服务器只发 message 事件，不使用独立 socket 事件通道
    const unsubTurnStart = () => {}
    const unsubTurnEnd = () => {}
    const unsubAgentResponse = socketStore.onAgentResponse('chat', (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'running')
      // 收到 agent_response 时隐藏对话框
      permissionDialog.visible = false
      agentQueryDialog.visible = false
    })
    const unsubToolCall = socketStore.onToolCall('chat', (m: Message) => {
      const targetAgentId = m.sender_id || agentStore.currentAgentId
      agentStore.updateAgentStatus(targetAgentId, 'running')
      // 收到 tool_call 时隐藏对话框
      permissionDialog.visible = false
      agentQueryDialog.visible = false
    })
    const unsubPermission = socketStore.onPermissionRequest('chat', (m: Message) => {
      permissionDialog.visible = true
      permissionDialog.requestId = m.data?.request_id
      permissionDialog.senderId = m.sender_id
      permissionDialog.message = m.data?.message || 'Permission required'
      permissionDialog.requestType = m.data?.request_type || 'general'
    })
    const unsubAgentQuery = socketStore.onAgentQuery('chat', (m: Message) => {
      agentQueryDialog.visible = true
      agentQueryDialog.requestId = m.data?.request_id
      agentQueryDialog.senderId = m.sender_id
      agentQueryDialog.question = m.data?.question || m.data?.content || ''
      agentQueryDialog.options = m.data?.options || []
    })

    // 保存注销函数以便 cleanup 时清理
    _cleanupHandlers.push(unsubMessage, unsubTurnStart, unsubTurnEnd,
      unsubAgentResponse, unsubToolCall, unsubPermission, unsubAgentQuery)

    await socketStore.connect()
  }

  const doSubscribe = async () => {
    // 订阅会话频道（不订阅编排事件），保存取消订阅函数以便 cleanup
    const unsub = await socketStore.subscribe(sessionId.value, false)
    _cleanupHandlers.push(unsub)
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

  const respondPermission = async (granted: boolean, sessionAction?: string) => {
    await socketStore.respondPermission({
      granted,
      session_action: sessionAction,
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
    agentStore.clearCache()
    // 清理 Runner 状态
    stopRunnerPolling()
    runnerInfo.value = null
  }

  const autoConnectAndSubscribe = async (execId?: string) => {
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
    executionId.value = execId

    try {
      await agentStore.fetchAgents(urlSessionId.value)
      await doConnect()
      await doSubscribe()

      // 恢复上次保存的显示模式
      displayMode.value = loadDisplayMode(sessionId.value)
      if (displayMode.value === 'concise') {
        await loadTurnHistory(sessionId.value, false, executionId.value)
        // 如果 turn 数据为空，加载消息历史用于降级检测（旧会话可能无 turn 聚合数据）
        if (turnSummaries.value.length === 0) {
          await loadHistory(sessionId.value, false, executionId.value)
          // 有消息但无 turn → 降级到明细模式
          if (messages.value.length > 0) {
            displayMode.value = 'detail'
          }
        }
        if (displayMode.value === 'detail') {
          // 已由降级条件加载了消息历史
        } else {
          startDurationTimer()
        }
      } else {
        await loadHistory(sessionId.value, false, executionId.value)
      }

      // 获取 Runner 状态并启动轮询
      await fetchRunnerStatus()
      startRunnerPolling()
    } catch (error: any) {
      console.error('自动连接失败:', error)
      sessionId.value = ''
      const { ElMessage } = await import('element-plus')
      ElMessage.error('连接会话失败: ' + (error.message || '未知错误'))
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
    // 清理当前页面注册的处理器
    _cleanupHandlers.forEach(fn => fn())
    _cleanupHandlers.length = 0
    connectingSession.value = false
    sessionId.value = ''
    agentStore.agents = []
    messages.value = []
    messageStates.value.clear()
    pendingChunks.value.clear()
    // 清理简洁模式状态
    stopDurationTimer()
    turnSummaries.value = []
    _turnLastResponseMsgId.clear()
    _turnSeenToolCallIds.clear()
    displayMode.value = 'concise'
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
    executionId,
    showRedoButton,
    redoReceiverId,
    isAgentOrchestration,
    messagesContainer,
    showLeftSidebar,
    showRightSidebar,
    isMobile,
    urlSessionId,
    permissionDialog,
    agentQueryDialog,
    messages,
    filteredMessages,
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
    // 简洁模式
    displayMode,
    turnSummaries,
    filteredTurnSummaries,
    loadingMoreTurns,
    hasMoreTurns,
    loadTurnHistory,
    toggleDisplayMode,
    startDurationTimer,
    stopDurationTimer,
    pendingScrollPercentage,
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
