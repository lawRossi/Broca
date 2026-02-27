<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores'
import { BrocaSocketClient, type BrocaMessage } from '@/api/brocaSocket'
import { sessionApi} from '@/api/session'

// 消息显示类型枚举，参考tui_app.py
enum DisplayType {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
  ERROR = 'error',
  THINKING = 'thinking',
  TOOL_CALL = 'tool_call',
}

type UiMessage = {
  id: string
  ts: string
  type: string
  displayType: DisplayType
  sender?: string
  receiver?: string
  subscription?: string
  content?: string
  raw: BrocaMessage
  showParameters?: boolean  // 用于控制 tool_call 消息的 parameters 显示
}

type AgentStatus = 'idle' | 'running' | 'connecting' | 'disconnected'

const route = useRoute()
const userStore = useUserStore()

// 状态管理
const connected = ref(false)
const connecting = ref(false)
const sessionId = ref<string>('')
const agentId = ref('main_agent')
const agentName = ref('Assistant')
const agentStatus = ref<AgentStatus>('disconnected')
const input = ref('')
const loading = ref(false)
const messagesContainer = ref<HTMLElement>()

// 移动端侧边栏控制
const showLeftSidebar = ref(false)
const showRightSidebar = ref(false)
const isMobile = ref(false)

// 检测是否为移动端
const checkMobile = () => {
  isMobile.value = window.innerWidth < 1024
  if (!isMobile.value) {
    showLeftSidebar.value = true
    showRightSidebar.value = true
  }
}

// 切换侧边栏显示
const toggleLeftSidebar = () => {
  showLeftSidebar.value = !showLeftSidebar.value
  if (showLeftSidebar.value) showRightSidebar.value = false
}

const toggleRightSidebar = () => {
  showRightSidebar.value = !showRightSidebar.value
  if (showRightSidebar.value) showLeftSidebar.value = false
}

// 消息过滤
const messageFilters = reactive({
  showUser: true,
  showAssistant: true,
  showSystem: true,
  showError: true,
})

// 从URL参数获取session_id
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

// 过滤后的消息
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
        return messageFilters.showAssistant // tool_call消息跟随assistant的过滤设置
      default:
        return true
    }
  })
})

// 添加UI消息
const addUiMessage = (m: BrocaMessage, displayType?: DisplayType) => {
  if (m.message_type === 'turn_start' || m.message_type === 'turn_end') {
    return
  }

  if (m.message_type === 'command') {
    return
  }

  // 不展示 connected to 和 subscribed to 消息
  const contentStr = m.data?.content ?? m.data?.message ?? ''
  if (typeof contentStr === 'string' && (contentStr.toLowerCase().includes('connected to') || contentStr.toLowerCase().includes('subscribed to'))) {
    return
  }

  // 检查是否是assistant消息且包含tool_call
  if ((m.message_type === 'agent_response' || m.role === 'assistant') && m.data?.content) {
    try {
      const contentObj = JSON.parse(m.data.content)
      
      // 检查是否有tool_calls字段（OpenAI格式）
      if (contentObj.tool_calls && Array.isArray(contentObj.tool_calls) && contentObj.tool_calls.length > 0) {
        // 首先添加content/reasoning content作为assistant消息（如果有的话）
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
          
          const assistantMsg: UiMessage = {
            id: `${m.message_id}_content`,
            ts: m.timestamp,
            type: m.message_type,
            displayType: DisplayType.ASSISTANT,
            sender: m.sender_id,
            receiver: m.receiver_id,
            subscription: m.subscription,
            content: assistantContent,
            raw: {
              ...m,
              data: { ...m.data, content: assistantContent }
            },
            showParameters: false,
          }
          
          uiMessages.value.push(assistantMsg)
        }
        
        // 然后为每个tool_call添加单独的消息
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
          
          const toolCallMsg: UiMessage = {
            id: `${m.message_id}_toolcall_${index}`,
            ts: m.timestamp,
            type: 'tool_call',
            displayType: DisplayType.TOOL_CALL,
            sender: m.sender_id,
            receiver: m.receiver_id,
            subscription: m.subscription,
            content: `🔧 Tool Call: ${toolName}`,
            raw: {
              message_id: `${m.message_id}_toolcall_${index}`,
              timestamp: m.timestamp,
              message_type: 'tool_call',
              sender_id: m.sender_id,
              receiver_id: m.receiver_id,
              subscription: m.subscription,
              data: {
                tool_name: toolName,
                arguments: argumentsData
              }
            },
            showParameters: false,
          }
          
          uiMessages.value.push(toolCallMsg)
        })
        
        // 自动滚动到底部
        nextTick(() => {
          scrollToBottom()
        })
        return
      }
    } catch (e) {
      // 如果不是JSON格式，继续正常处理
      console.debug('消息内容不是有效的JSON格式:', e)
    }
  }

  // 使用统一的消息处理函数处理其他消息
  const processed = processMessageForDisplay(m, m.message_type)
  
  const uiMsg: UiMessage = {
    id: m.message_id,
    ts: m.timestamp,
    type: m.message_type,
    displayType: displayType || processed.displayType,
    sender: m.sender_id,
    receiver: m.receiver_id,
    subscription: m.subscription,
    content: processed.content,
    raw: m,
    showParameters: false, // 默认不显示参数
  }

  uiMessages.value.push(uiMsg)

  // 自动滚动到底部
  nextTick(() => {
    scrollToBottom()
  })
}

// 添加系统消息
const addSystemMessage = (content: string) => {
  const msg: UiMessage = {
    id: `system_${Date.now()}`,
    ts: new Date().toISOString(),
    type: 'system',
    displayType: DisplayType.SYSTEM,
    sender: 'system',
    content,
    raw: {} as BrocaMessage,
  }
  uiMessages.value.push(msg)
  nextTick(() => {
    scrollToBottom()
  })
}

// 滚动到底部
const scrollToBottom = () => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// 切换tool_call消息的参数显示
const toggleToolParameters = (messageId: string) => {
  const message = uiMessages.value.find(m => m.id === messageId)
  if (message && message.displayType === DisplayType.TOOL_CALL) {
    message.showParameters = !message.showParameters
  }
}


let client: BrocaSocketClient | null = null

// 状态文本
const statusText = computed(() => {
  if (connecting.value) return 'connecting'
  return connected.value ? 'connected' : 'disconnected'
})

// Agent状态文本
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


// 根据session_id获取agent_id和agent_name
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

// 解析消息内容
const parseMessageContent = (content: string | undefined): string => {
  if (!content) return ''
  try {
    const parsed = JSON.parse(content)
    
    // 如果消息包含tool_calls，则返回原始JSON字符串，让processMessageForDisplay处理
    if (parsed.tool_calls && Array.isArray(parsed.tool_calls) && parsed.tool_calls.length > 0) {
      return JSON.stringify(parsed, null, 2)
    }
    
    // 优先返回content字段，如果没有则返回整个JSON字符串
    return parsed.content || JSON.stringify(parsed, null, 2)
  } catch {
    return content
  }
}

// 统一的消息显示处理函数
const processMessageForDisplay = (messageData: any, messageType?: string): { 
  content: string, 
  displayType: DisplayType, 
  data?: any 
} => {
  // 优先使用传入的messageType，否则从messageData中获取
  const msgType = messageType || messageData.message_type
  
  // 处理tool_call消息
  if (msgType === 'tool_call') {
    let toolName = 'unknown_tool'
    let argumentsData = {}
    
    // 尝试从不同位置获取数据
    if (messageData.data?.tool_name) {
      // 实时消息格式
      toolName = messageData.data.tool_name
      argumentsData = messageData.data.arguments || {}
    } else if (messageData.content) {
      // 历史消息格式（JSON字符串）
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
      content: `🔧 Tool Call: ${toolName}`,
      displayType: DisplayType.TOOL_CALL,
      data: {
        tool_name: toolName,
        arguments: argumentsData
      }
    }
  }
  
  // 处理tool_result消息
  if (msgType === 'tool_result') {
    let result = '无结果'
    
    // 尝试从不同位置获取数据
    if (messageData.data?.result !== undefined) {
      // 实时消息格式
      result = messageData.data.result
    } else if (messageData.content) {
      // 历史消息格式（JSON字符串）
      try {
        const parsedContent = JSON.parse(messageData.content)
        result = parsedContent.result || result
      } catch (e) {
        result = messageData.content
      }
    }
    
    const displayResult = typeof result === 'string' 
      ? (result.length > 100 ? result.substring(0, 100) + '...' : result)
      : JSON.stringify(result, null, 2)
    
    return {
      content: `✅ Tool Result: ${displayResult}`,
      displayType: DisplayType.ASSISTANT
    }
  }
  
  // 处理普通消息
  let content = ''
  if (messageData.data?.content !== undefined) {
    // 实时消息格式
    content = messageData.data.content
  } else if (messageData.content) {
    // 历史消息格式
    content = parseMessageContent(messageData.content)
  } else if (messageData.data?.message) {
    content = messageData.data.message
  } else if (messageData.error_message) {
    content = messageData.error_message
  }
  
  // 确定显示类型
  let displayType = DisplayType.ASSISTANT
  if (msgType === 'error' || messageData.error_message) {
    displayType = DisplayType.ERROR
  } else if (messageData.sender_id === 'system' || messageData.sender_id?.includes('system')) {
    displayType = DisplayType.SYSTEM
  } else if (messageData.sender_id === 'user' || messageData.sender_id?.includes('user') || messageData.role === 'user') {
    displayType = DisplayType.USER
  } else if (msgType === 'tool_call') {
    displayType = DisplayType.TOOL_CALL
  }
  
  return {
    content,
    displayType
  }
}

// 加载历史对话
const loadHistory = async (sessionId: string) => {
  try {
    loading.value = true
    const response = await sessionApi.getSessionMessages(sessionId)
    if (response.messages) {
      const filteredMessages = response.messages.filter(
        (msg: any) => (msg.role === 'user' || msg.role === 'assistant') && 
                     (parseMessageContent(msg.content) || msg.message_type === 'tool_call') && 
                     msg.message_type !== 'command'
      )
      
      const historyMessages: UiMessage[] = []
      
      filteredMessages.forEach((msg: any) => {
        // 检查是否是assistant消息且包含tool_call
        if ((msg.role === 'assistant' || msg.message_type === 'agent_response') && msg.content) {
          try {
            const contentObj = JSON.parse(msg.content)
            
            // 检查是否有tool_calls字段（OpenAI格式）
            if (contentObj.tool_calls && Array.isArray(contentObj.tool_calls) && contentObj.tool_calls.length > 0) {
              // 首先添加content/reasoning content作为assistant消息（如果有的话）
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
                
                const assistantMsg: UiMessage = {
                  id: `${msg.message_id}_content`,
                  ts: msg.timestamp,
                  type: msg.message_type,
                  displayType: DisplayType.ASSISTANT,
                  sender: msg.role === 'user' ? 'user' : msg.agent_id,
                  receiver: msg.role === 'user' ? msg.agent_id : 'user',
                  subscription: sessionId,
                  content: assistantContent,
                  raw: {
                    message_id: `${msg.message_id}_content`,
                    timestamp: msg.timestamp,
                    message_type: msg.message_type,
                    sender_id: msg.role === 'user' ? 'user' : msg.agent_id,
                    receiver_id: msg.role === 'user' ? msg.agent_id : 'user',
                    subscription: sessionId,
                    data: { content: assistantContent }
                  } as BrocaMessage,
                  showParameters: false,
                }
                
                historyMessages.push(assistantMsg)
              }
              
              // 然后为每个tool_call添加单独的消息
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
                
                const toolCallMsg: UiMessage = {
                  id: `${msg.message_id}_toolcall_${index}`,
                  ts: msg.timestamp,
                  type: 'tool_call',
                  displayType: DisplayType.TOOL_CALL,
                  sender: msg.role === 'user' ? 'user' : msg.agent_id,
                  receiver: msg.role === 'user' ? msg.agent_id : 'user',
                  subscription: sessionId,
                  content: `🔧 Tool Call: ${toolName}`,
                  raw: {
                    message_id: `${msg.message_id}_toolcall_${index}`,
                    timestamp: msg.timestamp,
                    message_type: 'tool_call',
                    sender_id: msg.role === 'user' ? 'user' : msg.agent_id,
                    receiver_id: msg.role === 'user' ? msg.agent_id : 'user',
                    subscription: sessionId,
                    data: {
                      tool_name: toolName,
                      arguments: argumentsData
                    }
                  } as BrocaMessage,
                  showParameters: false,
                }
                
                historyMessages.push(toolCallMsg)
              })
              
              return // 跳过正常的消息处理
            }
          } catch (e) {
            // 如果不是JSON格式，继续正常处理
            console.debug('历史消息内容不是有效的JSON格式:', e)
          }
        }
        
        // 使用统一的消息处理函数处理其他消息
        const processed = processMessageForDisplay(msg, msg.message_type)
        
        // 构建raw消息数据 - 确保与实时消息格式一致
        const rawData: any = { content: processed.content }
        if (processed.data) {
          Object.assign(rawData, processed.data)
        }
        
        const uiMsg: UiMessage = {
          id: msg.message_id,
          ts: msg.timestamp,
          type: msg.message_type,
          displayType: processed.displayType,
          sender: msg.role === 'user' ? 'user' : msg.agent_id,
          receiver: msg.role === 'user' ? msg.agent_id : 'user',
          subscription: sessionId,
          content: processed.content,
          raw: {
            message_id: msg.message_id,
            timestamp: msg.timestamp,
            message_type: msg.message_type,
            sender_id: msg.role === 'user' ? 'user' : msg.agent_id,
            receiver_id: msg.role === 'user' ? msg.agent_id : 'user',
            subscription: sessionId,
            data: rawData
          } as BrocaMessage,
          showParameters: false // 默认不显示参数
        }
        
        historyMessages.push(uiMsg)
      })
      
      uiMessages.value = [...historyMessages, ...uiMessages.value]
    }
  } catch (error: any) {
    console.error('加载历史消息失败:', error)
  } finally {
    loading.value = false
  }
}

// 自动连接和订阅
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
  } catch (error: any) {
    console.error('自动连接失败:', error)
    ElMessage.error(`自动连接失败: ${error.message || '未知错误'}`)
  }
}

// 命令处理
const handleCommand = async (cmd: string, args: string[]) => {
  switch (cmd.toLowerCase()) {
    case 'help':
      const helpText = `Available commands:
  /help      - Show this help message
  /clear     - Clear chat history
  /status    - Show connection status
  /history   - Show command history
  /filter    - Toggle message filters
  /quit      - Disconnect from server

Keyboard shortcuts:
  Enter      - Send message
  Ctrl+L     - Clear chat`
      addSystemMessage(helpText)
      break
    case 'clear':
      uiMessages.value = []
      addSystemMessage('Chat history cleared')
      break
    case 'status':
      const statusInfo = `Connection Status:
  Server: ${socketConfig.serverUrl}
  Client ID: ${socketConfig.clientId}
  Session: ${sessionId.value || '未设置'}
  Agent: ${agentId.value}
  Status: ${statusText.value}
  Agent Status: ${agentStatus.value}
  Messages: ${uiMessages.value.length}`
      addSystemMessage(statusInfo)
      break
    case 'filter':
      if (args.length === 0) {
        // 切换所有过滤器
        const allEnabled = messageFilters.showUser && messageFilters.showAssistant && messageFilters.showSystem
        messageFilters.showUser = !allEnabled
        messageFilters.showAssistant = !allEnabled
        messageFilters.showSystem = !allEnabled
        messageFilters.showError = !allEnabled
        addSystemMessage(`All message filters: ${!allEnabled ? 'ON' : 'OFF'}`)
      } else {
        const filterType = args[0].toLowerCase()
        switch (filterType) {
          case 'user':
            messageFilters.showUser = !messageFilters.showUser
            addSystemMessage(`User messages: ${messageFilters.showUser ? 'ON' : 'OFF'}`)
            break
          case 'assistant':
            messageFilters.showAssistant = !messageFilters.showAssistant
            addSystemMessage(`Assistant messages: ${messageFilters.showAssistant ? 'ON' : 'OFF'}`)
            break
          case 'system':
            messageFilters.showSystem = !messageFilters.showSystem
            addSystemMessage(`System messages: ${messageFilters.showSystem ? 'ON' : 'OFF'}`)
            break
          case 'error':
            messageFilters.showError = !messageFilters.showError
            addSystemMessage(`Error messages: ${messageFilters.showError ? 'ON' : 'OFF'}`)
            break
          default:
            addSystemMessage(`Unknown filter type: ${filterType}`)
        }
      }
      break
    case 'quit':
    case 'exit':
      addSystemMessage('Goodbye!')
      if (client) {
        await client.disconnect()
      }
      connected.value = false
      agentStatus.value = 'disconnected'
      break
    default:
      addSystemMessage(`Unknown command: /${cmd}`)
      handleCommand('help', [])
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
    client.on('message', (m: BrocaMessage) => addUiMessage(m))
    
    // 监听turn_start和turn_end事件
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

const send = async () => {
  if (!client) {
    ElMessage.warning('请先连接')
    return
  }
  const text = input.value.trim()
  if (!text) return

  input.value = ''

  // 命令格式
  if (text.startsWith('/')) {
    const [cmd, ...rest] = text.slice(1).split(' ')
    await handleCommand(cmd, rest)
    return
  }

  // 添加用户消息到显示
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

// 发送 abort 命令
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

// 监听URL参数变化
watch(urlSessionId, (newSessionId) => {
  if (newSessionId && newSessionId !== sessionId.value) {
    sessionId.value = newSessionId
    if (connected.value) {
      doSubscribe()
      loadHistory(newSessionId)
    }
  }
})

onMounted(async () => {
  await userStore.init()
  
  // 初始化移动端检测
  checkMobile()
  window.addEventListener('resize', checkMobile)
  
  if (urlSessionId.value) {
    autoConnectAndSubscribe()
  }
})

// 清理事件监听
onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})
</script>

<template>
  <div class="h-screen bg-gray-50 flex flex-col overflow-hidden">
    <!-- 加载状态 -->
    <div v-if="loading" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60]">
      <div class="bg-white p-6 rounded-lg shadow-lg">
        <div class="flex items-center space-x-3">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          <div class="text-gray-700">加载中...</div>
        </div>
      </div>
    </div>

    <!-- Top status bar with agent status - Fixed positioning -->
    <div class="flex-shrink-0 bg-white border-b shadow-sm">
      <div class="mx-auto max-w-7xl px-3 sm:px-4 py-2 sm:py-3">
        <div class="flex items-center justify-between gap-2">
          <!-- Left: Logo and connection status -->
          <div class="flex items-center gap-2 sm:gap-3">
            <div class="font-bold text-lg sm:text-xl text-gray-900">Broca</div>
            <el-tag :type="connected ? 'success' : connecting ? 'warning' : 'info'" size="small" class="hidden sm:inline">
              {{ statusText }}
            </el-tag>
            <!-- Mobile status indicator -->
            <div class="sm:hidden w-2 h-2 rounded-full" :class="{
              'bg-green-500': connected,
              'bg-yellow-500': connecting,
              'bg-gray-400': !connected && !connecting
            }"></div>
          </div>

          <!-- Center: Agent status indicator -->
          <div class="flex items-center gap-2 sm:gap-4 flex-1 justify-center">
            <div class="flex items-center gap-1.5 sm:gap-2">
              <div class="w-2 h-2 rounded-full flex-shrink-0" :class="{
                'bg-green-500': agentStatus === 'idle',
                'bg-yellow-500 animate-pulse': agentStatus === 'running',
                'bg-blue-500 animate-pulse': agentStatus === 'connecting',
                'bg-gray-400': agentStatus === 'disconnected'
              }"></div>
              <span class="text-xs sm:text-sm font-medium truncate max-w-[100px] sm:max-w-none" :class="{
                'text-green-700': agentStatus === 'idle',
                'text-yellow-700': agentStatus === 'running',
                'text-blue-700': agentStatus === 'connecting',
                'text-gray-500': agentStatus === 'disconnected'
              }">{{ agentStatusText }}</span>
            </div>
            <div v-if="agentId && agentStatus !== 'disconnected'" class="hidden md:block text-xs text-gray-500">
              Agent: {{ agentId }}
            </div>
          </div>

          <!-- Right: Mobile menu buttons and Client info -->
          <div class="flex items-center gap-2">
            <!-- Mobile sidebar toggle buttons -->
            <div class="lg:hidden flex items-center gap-1">
              <el-button 
                :type="showLeftSidebar ? 'primary' : 'default'"
                size="small"
                class="!px-2"
                @click="toggleLeftSidebar"
              >
                <span class="text-xs">⚙️</span>
              </el-button>
              <el-button 
                :type="showRightSidebar ? 'primary' : 'default'"
                size="small"
                class="!px-2"
                @click="toggleRightSidebar"
              >
                <span class="text-xs">📊</span>
              </el-button>
            </div>
            <!-- Desktop client info -->
            <div class="hidden sm:block text-xs text-gray-500">
              client: {{ socketConfig.clientId.slice(0, 8) }}...
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Main content area - Fill remaining height -->
    <div class="flex-1 mx-auto max-w-7xl w-full px-2 sm:px-4 py-2 sm:py-4 overflow-hidden">
      <div class="grid grid-cols-12 gap-2 sm:gap-4 h-full">

        <!-- Left sidebar: Filters and Controls - Fixed -->
        <div 
          class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
          :class="{
            'flex': !isMobile || showLeftSidebar,
            'hidden': isMobile && !showLeftSidebar,
            'absolute inset-x-2 top-20 bottom-4 z-40 bg-gray-50 p-3 rounded-lg shadow-xl border': isMobile && showLeftSidebar
          }"
        >

          <!-- Mobile sidebar header with close button -->
          <div v-if="isMobile && showLeftSidebar" class="flex justify-between items-center lg:hidden">
            <span class="text-sm font-semibold text-gray-700">Settings</span>
            <el-button size="small" @click="showLeftSidebar = false">✕</el-button>
          </div>

          <!-- Message Filters -->
          <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
            <div class="text-sm font-semibold text-gray-900 mb-3">Message Filters</div>
            <div class="space-y-2">
              <el-checkbox v-model="messageFilters.showUser" size="small">
                <span class="flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-blue-500"></span>
                  User Messages
                </span>
              </el-checkbox>
              <el-checkbox v-model="messageFilters.showAssistant" size="small">
                <span class="flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-green-500"></span>
                  Assistant
                </span>
              </el-checkbox>
              <el-checkbox v-model="messageFilters.showSystem" size="small">
                <span class="flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-gray-500"></span>
                  System
                </span>
              </el-checkbox>
              <el-checkbox v-model="messageFilters.showError" size="small">
                <span class="flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-red-500"></span>
                  Errors
                </span>
              </el-checkbox>
            </div>
            
            <div class="mt-4 pt-3 border-t text-xs text-gray-500">
              Showing {{ filteredMessages.length }} of {{ uiMessages.length }} messages
            </div>
          </div>

          <!-- Quick Commands -->
          <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
            <div class="text-sm font-semibold text-gray-900 mb-3">Quick Commands</div>
            <div class="space-y-1 text-xs">
              <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="input = '/help'">
                <code class="bg-gray-100 px-1 rounded">/help</code>
                <span class="text-gray-600">Show help</span>
              </div>
              <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="input = '/clear'">
                <code class="bg-gray-100 px-1 rounded">/clear</code>
                <span class="text-gray-600">Clear chat</span>
              </div>
              <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="input = '/status'">
                <code class="bg-gray-100 px-1 rounded">/status</code>
                <span class="text-gray-600">Show status</span>
              </div>
              <div class="flex items-center gap-2 p-1 hover:bg-gray-50 rounded cursor-pointer" @click="input = '/filter'">
                <code class="bg-gray-100 px-1 rounded">/filter</code>
                <span class="text-gray-600">Toggle filters</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Middle: Message list - Scrollable -->
        <div 
          class="flex flex-col gap-2 sm:gap-4 h-full overflow-hidden"
          :class="{
            'col-span-12 lg:col-span-6': true,
            'hidden lg:flex': (isMobile && showLeftSidebar) || (isMobile && showRightSidebar)
          }"
        >
          <div
            ref="messagesContainer"
            class="flex-1 bg-white rounded-lg border shadow-sm overflow-y-auto p-4 space-y-3"
          >
            <!-- Empty state -->
            <div v-if="!filteredMessages.length" class="flex flex-col items-center justify-center h-full text-gray-400">
              <div class="text-4xl mb-2">💬</div>
              <div v-if="urlSessionId && !connected" class="text-sm">正在自动连接...</div>
              <div v-else-if="urlSessionId && connected" class="text-sm">已连接，等待消息...</div>
              <div v-else class="text-sm">未设置session_id。请手动输入或通过URL参数传入。</div>
            </div>

            <!-- Message items with type-specific styling -->
            <div
              v-for="m in filteredMessages"
              :key="m.id"
              class="rounded-lg p-2 sm:p-3 transition-all duration-200"
              :class="{
                // User messages - blue theme (smaller margin on mobile)
                'bg-blue-50 border-l-4 border-blue-500 ml-4 sm:ml-8': m.displayType === DisplayType.USER,
                // Assistant messages - green theme (smaller margin on mobile)
                'bg-green-50 border-l-4 border-green-500 mr-4 sm:mr-8': m.displayType === DisplayType.ASSISTANT,
                // System messages - gray theme, centered
                'bg-gray-100 border border-gray-200 text-center text-gray-600 text-xs sm:text-sm': m.displayType === DisplayType.SYSTEM,
                // Error messages - red theme
                'bg-red-50 border-l-4 border-red-500 text-red-800': m.displayType === DisplayType.ERROR,
                // Thinking messages - yellow theme
                'bg-yellow-50 border-l-4 border-yellow-500 italic': m.displayType === DisplayType.THINKING,
                // Tool call messages - purple theme
                'bg-purple-50 border-l-4 border-purple-500': m.displayType === DisplayType.TOOL_CALL,
              }"
            >
              <!-- Message header -->
              <div 
                v-if="m.displayType !== DisplayType.SYSTEM"
                class="flex items-center justify-between gap-2 mb-2"
              >
                <div class="flex items-center gap-2">
                  <!-- Type icon -->
                  <span class="text-lg">
                    {{ 
                      m.displayType === DisplayType.USER ? '👤' : 
                      m.displayType === DisplayType.ASSISTANT ? '🤖' : 
                      m.displayType === DisplayType.ERROR ? '⚠️' : 
                      m.displayType === DisplayType.THINKING ? '💭' : 
                      m.displayType === DisplayType.TOOL_CALL ? '🔧' : '💬' 
                    }}
                  </span>
                  <!-- Sender name -->
                  <span class="font-semibold text-sm" :class="{
                    'text-blue-700': m.displayType === DisplayType.USER,
                    'text-green-700': m.displayType === DisplayType.ASSISTANT,
                    'text-red-700': m.displayType === DisplayType.ERROR,
                    'text-yellow-700': m.displayType === DisplayType.THINKING,
                    'text-purple-700': m.displayType === DisplayType.TOOL_CALL,
                  }">
                    {{
                      m.displayType === DisplayType.USER ? 'You' :
                      m.displayType === DisplayType.ASSISTANT ? agentName :
                      m.displayType === DisplayType.ERROR ? 'Error' :
                      m.displayType === DisplayType.THINKING ? 'Thinking' :
                      m.displayType === DisplayType.TOOL_CALL ? 'Tool Call' : 'System'
                    }}
                  </span>
                </div>
                <!-- Timestamp -->
                <div class="text-xs opacity-70">
                  {{ new Date(m.ts).toLocaleTimeString() }}
                </div>
              </div>
              
              <!-- Message content -->
              <div>
                <pre 
                  class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-2"
                  :class="{
                    'text-gray-800': m.displayType === DisplayType.USER || m.displayType === DisplayType.ASSISTANT,
                    'font-mono': m.displayType === DisplayType.SYSTEM,
                    'text-purple-800': m.displayType === DisplayType.TOOL_CALL,
                  }"
                >{{ m.content }}</pre>
                
                <!-- Tool call parameters (only for tool_call messages) -->
                <div v-if="m.displayType === DisplayType.TOOL_CALL && m.raw.data?.arguments" class="mt-2">
                  <el-button 
                    size="small" 
                    type="text" 
                    @click="toggleToolParameters(m.id)"
                    class="!text-purple-600 !p-0 !h-auto !min-h-0"
                  >
                    {{ m.showParameters ? '隐藏参数' : '查看参数' }}
                  </el-button>
                  
                  <div v-if="m.showParameters" class="mt-2 p-2 bg-purple-100 rounded border border-purple-200">
                    <div class="text-xs font-semibold text-purple-700 mb-1">参数:</div>
                    <pre class="text-xs font-mono text-purple-800 whitespace-pre-wrap break-words bg-white p-2 rounded border">
{{ JSON.stringify(m.raw.data.arguments, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Input area -->
          <div class="bg-white rounded-lg border shadow-sm p-2 sm:p-4">
            <div class="flex gap-2">
              <el-input
                v-model="input"
                placeholder="Type message..."
                @keyup.enter="send"
                :disabled="!connected"
                :size="isMobile ? 'default' : 'large'"
                clearable
              />
              <el-button 
                v-if="agentStatus === 'running'"
                type="danger" 
                @click="sendAbort"
                :size="isMobile ? 'default' : 'large'"
                title="Abort current operation"
              >
                <span class="hidden sm:inline">Abort</span>
                <span class="sm:hidden">⏹</span>
              </el-button>
              <el-button 
                type="primary" 
                @click="send" 
                :disabled="!connected || !input.trim()"
                :size="isMobile ? 'default' : 'large'"
              >
                <span class="hidden sm:inline">Send</span>
                <span class="sm:hidden">➤</span>
              </el-button>
            </div>
            <div class="mt-2 text-xs text-gray-400 flex justify-between">
              <span class="hidden sm:inline">Press Enter to send</span>
              <span v-if="!connected" class="text-red-500">Not connected</span>
            </div>
          </div>
        </div>

        <!-- Right: Session Info and Inspector - Fixed -->
        <div 
          class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
          :class="{
            'flex': !isMobile || showRightSidebar,
            'hidden': isMobile && !showRightSidebar,
            'absolute inset-x-2 top-20 bottom-4 z-40 bg-gray-50 p-3 rounded-lg shadow-xl border': isMobile && showRightSidebar
          }"
        >
          <!-- Mobile sidebar header with close button -->
          <div v-if="isMobile && showRightSidebar" class="flex justify-between items-center lg:hidden">
            <span class="text-sm font-semibold text-gray-700">Info</span>
            <el-button size="small" @click="showRightSidebar = false">✕</el-button>
          </div>

          <!-- Session Info -->
          <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
            <div class="text-sm font-semibold text-gray-900 mb-3">Session Info</div>
            <div class="space-y-3 text-sm">
              <div class="flex justify-between">
                <span class="text-gray-500">Session:</span>
                <span class="font-mono text-xs truncate max-w-[150px]" :title="sessionId">
                  {{ sessionId || '未设置' }}
                </span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-500">Agent:</span>
                <span class="font-mono text-xs">{{ agentId }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-500">Status:</span>
                <el-tag :type="connected ? 'success' : 'info'" size="small">{{ statusText }}</el-tag>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-500">Messages:</span>
                <span class="font-mono">{{ uiMessages.length }}</span>
              </div>
            </div>
          </div>

          <!-- Statistics -->
          <div class="bg-white rounded-lg border p-3 sm:p-4 shadow-sm">
            <div class="text-sm font-semibold text-gray-900 mb-3">Message Statistics</div>
            <div class="space-y-2">
              <div class="flex justify-between items-center">
                <span class="text-sm text-gray-600 flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-blue-500"></span>
                  User
                </span>
                <span class="font-mono text-sm">{{ uiMessages.filter(m => m.displayType === DisplayType.USER).length }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-sm text-gray-600 flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-green-500"></span>
                  Assistant
                </span>
                <span class="font-mono text-sm">{{ uiMessages.filter(m => m.displayType === DisplayType.ASSISTANT).length }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-sm text-gray-600 flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-gray-500"></span>
                  System
                </span>
                <span class="font-mono text-sm">{{ uiMessages.filter(m => m.displayType === DisplayType.SYSTEM).length }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-sm text-gray-600 flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-red-500"></span>
                  Errors
                </span>
                <span class="font-mono text-sm">{{ uiMessages.filter(m => m.displayType === DisplayType.ERROR).length }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-sm text-gray-600 flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-purple-500"></span>
                  Tool Calls
                </span>
                <span class="font-mono text-sm">{{ uiMessages.filter(m => m.displayType === DisplayType.TOOL_CALL).length }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Permission Dialog -->
    <el-dialog 
      v-model="permissionDialog.visible" 
      title="Permission Request" 
      :width="isMobile ? '90%' : '520px'" 
      :close-on-click-modal="false"
    >
      <div class="flex items-start gap-3">
        <div class="text-3xl">🔐</div>
        <div class="text-sm text-gray-700 whitespace-pre-wrap flex-1">{{ permissionDialog.message }}</div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <el-button @click="respondPermission(false)">Deny</el-button>
          <el-button type="primary" @click="respondPermission(true)">Allow</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* Custom scrollbar for message container */
.overflow-y-auto::-webkit-scrollbar {
  width: 8px;
}

.overflow-y-auto::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.overflow-y-auto::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

.overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

/* Animations */
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.animate-pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

/* Message hover effect */
.rounded-lg {
  transition: all 0.2s ease;
}

.rounded-lg:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* Mobile touch optimizations */
@media (max-width: 1023px) {
  /* Larger touch targets for mobile */
  .el-button {
    min-height: 36px;
    min-width: 36px;
  }

  /* Better scrolling on mobile */
  .overflow-y-auto {
    -webkit-overflow-scrolling: touch;
  }

  /* Prevent text selection on UI elements */
  .el-button,
  .el-checkbox {
    user-select: none;
    -webkit-user-select: none;
  }

  /* Optimize tap highlight */
  * {
    -webkit-tap-highlight-color: transparent;
  }

  /* Ensure inputs are properly sized on mobile */
  input,
  textarea {
    font-size: 16px; /* Prevents zoom on iOS */
  }
}

/* Safe area insets for notched phones */
@supports (padding: max(0px)) {
  .h-screen {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
    padding-bottom: max(0px, env(safe-area-inset-bottom));
  }
}
</style>
