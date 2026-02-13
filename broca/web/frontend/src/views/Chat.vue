<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores'
import { BrocaSocketClient, type BrocaMessage } from '@/api/brocaSocket'
import { sessionApi} from '@/api/session'

type UiMessage = {
  id: string
  ts: string
  type: string
  sender?: string
  receiver?: string
  subscription?: string
  content?: string
  raw: BrocaMessage
}

const route = useRoute()
const userStore = useUserStore()

// 状态管理
const connected = ref(false)
const connecting = ref(false)
const sessionId = ref<string>('')
const agentId = ref('main_agent')
const input = ref('')
const loading = ref(false)

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

// 添加UI消息
const addUiMessage = (m: BrocaMessage) => {
  const content =
    m.data?.content ??
    m.data?.reasoning_content ??
    m.data?.message ??
    m.error_message ??
    JSON.stringify(m.data ?? {}, null, 2)

  uiMessages.value.push({
    id: m.message_id,
    ts: m.timestamp,
    type: m.message_type,
    sender: m.sender_id,
    receiver: m.receiver_id,
    subscription: m.subscription,
    content,
    raw: m,
  })
}

let client: BrocaSocketClient | null = null

const statusText = computed(() => {
  if (connecting.value) return 'connecting'
  return connected.value ? 'connected' : 'disconnected'
})

// 根据session_id获取agent_id
const fetchAgentId = async (sessionId: string) => {
  try {
    loading.value = true
    const latestAgent = await sessionApi.getSessionLatestAgent(sessionId)
    agentId.value = latestAgent.agent_id
  } catch (error: any) {
    console.error('获取Agent失败:', error)
    ElMessage.warning('获取Agent失败，使用默认Agent')
  } finally {
    loading.value = false
  }
}

// 解析消息内容，如果是JSON则提取content字段
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
      // 过滤只保留role为user和assistant的消息
      const filteredMessages = response.messages.filter(
        (msg: any) => (msg.role === 'user' || msg.role === 'assistant') && parseMessageContent(msg.content)
      )
      // 将历史消息转换为UI消息格式
      const historyMessages = filteredMessages.map((msg: any): UiMessage => ({
        id: msg.message_id,
        ts: msg.timestamp,
        type: msg.message_type,
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
      ElMessage.success(`已加载 ${historyMessages.length} 条历史消息`)
    }
  } catch (error: any) {
    console.error('加载历史消息失败:', error)
    ElMessage.warning('加载历史消息失败')
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

  // 设置session_id
  sessionId.value = urlSessionId.value

  try {
    // 获取agent_id
    await fetchAgentId(urlSessionId.value)
    
    // 连接WebSocket
    await doConnect()
    
    // 订阅session
    await doSubscribe()
    
    // 加载历史消息
    await loadHistory(urlSessionId.value)
    
  } catch (error: any) {
    console.error('自动连接失败:', error)
    ElMessage.error(`自动连接失败: ${error.message || '未知错误'}`)
  }
}

const doConnect = async () => {
  if (connected.value || connecting.value) return
  connecting.value = true
  try {
    client = new BrocaSocketClient({
      serverUrl: socketConfig.serverUrl,
      clientType: socketConfig.clientType,
      clientId: socketConfig.clientId,
      userId: socketConfig.userId,
    })

    // 事件监听
    client.on('connect', () => {
      connected.value = true
      connecting.value = false
      ElMessage.success('连接成功')
    })
    client.on('disconnect', () => {
      connected.value = false
      connecting.value = false
      ElMessage.warning('连接断开')
    })
    client.on('message', (m: BrocaMessage) => addUiMessage(m))
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
    ElMessage.success(`已订阅: ${sessionId.value.trim()}`)
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
    try {
      const commandParams: any = {
        command: cmd,
        receiverId: agentId.value,
        subscription: sessionId.value!,
      }
      if (rest.length) {
        commandParams.arguments = { args: rest }
      }
      await client.sendCommand(commandParams)
    } catch (e: any) {
      ElMessage.error(e?.message || '发送命令失败')
    }
    return
  }

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
    // 如果已经连接，重新订阅
    if (connected.value) {
      doSubscribe()
      loadHistory(newSessionId)
    }
  }
})

onMounted(async () => {
  await userStore.init()
  
  // 如果有URL参数，自动连接
  if (urlSessionId.value) {
    autoConnectAndSubscribe()
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 加载状态 -->
    <div v-if="loading" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white p-6 rounded-lg shadow-lg">
        <div class="flex items-center space-x-3">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          <div class="text-gray-700">加载中...</div>
        </div>
      </div>
    </div>

    <!-- Top status bar -->
    <div class="sticky top-0 z-10 bg-white border-b">
      <div class="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="font-semibold text-gray-900">Broca Web</div>
          <el-tag :type="connected ? 'success' : connecting ? 'warning' : 'info'">{{ statusText }}</el-tag>
          <div class="text-xs text-gray-500">client_id: {{ socketConfig.clientId }}</div>
        </div>
      </div>
    </div>

    <div class="mx-auto max-w-6xl px-4 py-6 grid grid-cols-12 gap-4">

      <!-- Middle: message list -->
      <div class="col-span-12 lg:col-span-6">
        <div class="bg-white rounded-lg border h-[70vh] overflow-auto p-3 space-y-2">
          <div v-if="!uiMessages.length" class="text-sm text-gray-500 py-10 text-center">
            <div v-if="urlSessionId && !connected">正在自动连接...</div>
            <div v-else-if="urlSessionId && connected">已连接，等待消息...</div>
            <div v-else>未设置session_id。请手动输入或通过URL参数传入。</div>
          </div>

          <div
            v-for="m in uiMessages"
            :key="m.id"
            class="rounded-md border px-3 py-2"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="text-xs text-gray-500">
                <span class="font-mono">{{ m.ts }}</span>
                <span class="mx-2">·</span>
                <el-tag size="small" effect="plain">{{ m.type }}</el-tag>
              </div>
              <div class="text-xs text-gray-400 font-mono">{{ m.id.slice(0, 8) }}</div>
            </div>
            <div class="mt-1 text-xs text-gray-500">
              <span v-if="m.sender">from: <span class="font-mono">{{ m.sender }}</span></span>
              <span v-if="m.receiver" class="ml-2">to: <span class="font-mono">{{ m.receiver }}</span></span>
              <span v-if="m.subscription" class="ml-2">sub: <span class="font-mono">{{ m.subscription }}</span></span>
            </div>
            <pre class="mt-2 text-sm text-gray-900 whitespace-pre-wrap break-words">{{ m.content }}</pre>
          </div>
        </div>

        <div class="mt-3 bg-white rounded-lg border p-3 flex gap-2">
          <el-input
            v-model="input"
            placeholder="Type message... (or /command)"
            @keyup.enter="send"
            :disabled="!connected"
          />
          <el-button type="primary" @click="send" :disabled="!connected">Send</el-button>
        </div>
      </div>

      <!-- Right: detail inspector -->
      <div class="col-span-12 lg:col-span-3">
        <div class="bg-white rounded-lg border p-4">
          <div class="text-sm font-semibold text-gray-900 mb-2">Session Info</div>
          <div class="text-xs text-gray-600 space-y-2">
            <div><strong>Session ID:</strong> {{ sessionId || '未设置' }}</div>
            <div><strong>Agent ID:</strong> {{ agentId }}</div>
            <div><strong>Status:</strong> {{ statusText }}</div>
            <div><strong>Messages:</strong> {{ uiMessages.length }}</div>
            <div v-if="urlSessionId" class="mt-2 p-2 bg-blue-50 rounded">
              <div class="text-blue-700 font-medium">URL参数模式</div>
              <div class="text-blue-600 text-xs mt-1">session_id从URL参数自动获取</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="permissionDialog.visible" title="Permission Request" width="520px">
      <div class="text-sm text-gray-700 whitespace-pre-wrap">{{ permissionDialog.message }}</div>
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
.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>