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
      default:
        return true
    }
  })
})

// 添加UI消息
const addUiMessage = (m: BrocaMessage, displayType?: DisplayType) => {
  // 不展示 turn_start 和 turn_end 消息
  if (m.message_type === 'turn_start' || m.message_type === 'turn_end') {
    return
  }

  // 不展示 connected to 和 subscribed to 消息
  const contentStr = m.data?.content ?? m.data?.message ?? ''
  if (typeof contentStr === 'string' && (contentStr.toLowerCase().includes('connected to') || contentStr.toLowerCase().includes('subscribed to'))) {
    return
  }

  let content =
    m.data?.content ??
    m.data?.reasoning_content ??
    m.data?.message ??
    m.error_message ??
    JSON.stringify(m.data ?? {}, null, 2)

  // tool_call 消息只展示 tool_name
  if (m.message_type === 'tool_call' && m.data?.tool_name) {
    content = `🔧 Tool Call: ${m.data.tool_name}`
  }

  // 自动判断消息类型
  let type = displayType
  if (!type) {
    if (m.message_type === 'error' || m.error_message) {
      type = DisplayType.ERROR
    } else if (m.sender_id === 'system' || m.sender_id?.includes('system')) {
      type = DisplayType.SYSTEM
    } else if (m.sender_id === 'user' || m.sender_id?.includes('user')) {
      type = DisplayType.USER
    } else {
      type = DisplayType.ASSISTANT
    }
  }

  const uiMsg: UiMessage = {
    id: m.message_id,
    ts: m.timestamp,
    type: m.message_type,
    displayType: type!,
    sender: m.sender_id,
    receiver: m.receiver_id,
    subscription: m.subscription,
    content,
    raw: m,
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

// Agent状态样式
const agentStatusClass = computed(() => {
  switch (agentStatus.value) {
    case 'idle':
      return 'bg-green-100 text-green-800'
    case 'running':
      return 'bg-yellow-100 text-yellow-800 animate-pulse'
    case 'connecting':
      return 'bg-blue-100 text-blue-800'
    case 'disconnected':
      return 'bg-gray-100 text-gray-800'
    default:
      return 'bg-gray-100 text-gray-800'
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
    return parsed.content
  } catch {
    return content
  }
}

// 加载历史对话
const loadHistory = async (sessionId: string) => {
  try {
    loading.value = true
    const response = await sessionApi.getSessionMessages(sessionId)
    if (response.messages) {
      const filteredMessages = response.messages.filter(
        (msg: any) => (msg.role === 'user' || msg.role === 'assistant') && parseMessageContent(msg.content)
      )
      
      const historyMessages = filteredMessages.map((msg: any): UiMessage => ({
        id: msg.message_id,
        ts: msg.timestamp,
        type: msg.message_type,
        displayType: msg.role === 'user' ? DisplayType.USER : DisplayType.ASSISTANT,
        sender: msg.role === 'user' ? 'user' : msg.agent_id,
        receiver: msg.role === 'user' ? msg.agent_id : 'user',
        subscription: sessionId,
        content: parseMessageContent(msg.content),
        raw: {
          message_id: msg.message_id,
          timestamp: msg.timestamp,
          message_type: msg.message_type,
          sender_id: msg.role === 'user' ? 'user' : msg.agent_id,
          receiver_id: msg.role === 'user' ? msg.agent_id : 'user',
          subscription: sessionId,
          data: { content: parseMessageContent(msg.content) }
        } as BrocaMessage
      }))
      
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
                      m.displayType === DisplayType.THINKING ? '💭' : '💬' 
                    }}
                  </span>
                  <!-- Sender name -->
                  <span class="font-semibold text-sm" :class="{
                    'text-blue-700': m.displayType === DisplayType.USER,
                    'text-green-700': m.displayType === DisplayType.ASSISTANT,
                    'text-red-700': m.displayType === DisplayType.ERROR,
                    'text-yellow-700': m.displayType === DisplayType.THINKING,
                  }">
                    {{
                      m.displayType === DisplayType.USER ? 'You' :
                      m.displayType === DisplayType.ASSISTANT ? agentName :
                      m.displayType === DisplayType.ERROR ? 'Error' :
                      m.displayType === DisplayType.THINKING ? 'Thinking' : 'System'
                    }}
                  </span>
                </div>
                <!-- Timestamp -->
                <div class="text-xs opacity-70">
                  {{ new Date(m.ts).toLocaleTimeString() }}
                </div>
              </div>
              
              <!-- Message content -->
              <pre 
                class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed"
                :class="{
                  'text-gray-800': m.displayType === DisplayType.USER || m.displayType === DisplayType.ASSISTANT,
                  'font-mono': m.displayType === DisplayType.SYSTEM,
                }"
              >{{ m.content }}</pre>
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
