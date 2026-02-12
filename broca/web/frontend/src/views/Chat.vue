<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores'
import { BrocaSocketClient, type BrocaMessage } from '@/api/brocaSocket'

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

const userStore = useUserStore()

const connected = ref(false)
const connecting = ref(false)
const sessionId = ref('')
const agentId = ref('main_agent')

const input = ref('')

const permissionDialog = reactive({
  visible: false,
  requestId: '' as string | undefined,
  senderId: '' as string | undefined,
  message: '',
})

const socketConfig = reactive({
  serverUrl: 'http://127.0.0.1:8000',
  clientType: 'browser',
  clientId: `browser_${Math.random().toString(16).slice(2)}`,
  userId: computed(() => userStore.userId || undefined),
})

const uiMessages = ref<UiMessage[]>([])

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

const doConnect = async () => {
  if (connected.value || connecting.value) return
  connecting.value = true
  try {
    client = new BrocaSocketClient({
      serverUrl: socketConfig.serverUrl,
      clientType: socketConfig.clientType,
      clientId: socketConfig.clientId,
      userId: socketConfig.userId.value,
    })

    // placeholders: once socket.io-client is available, these will work
    client.on('connect', () => {
      connected.value = true
      connecting.value = false
    })
    client.on('disconnect', () => {
      connected.value = false
      connecting.value = false
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
    ElMessage.error(e?.message || 'connect failed')
  }
}

const doSubscribe = async () => {
  if (!client) return
  if (!sessionId.value.trim()) {
    ElMessage.warning('请输入 session_id')
    return
  }
  try {
    await client.subscribe(sessionId.value.trim())
    ElMessage.success(`Subscribed: ${sessionId.value.trim()}`)
  } catch (e: any) {
    ElMessage.error(e?.message || 'subscribe failed')
  }
}

const send = async () => {
  if (!client) return
  const text = input.value.trim()
  if (!text) return

  input.value = ''

  // command style
  if (text.startsWith('/')) {
    const [cmd, ...rest] = text.slice(1).split(' ')
    try {
      await client.sendCommand({
        command: cmd,
        arguments: rest.length ? { args: rest } : undefined,
        receiverId: agentId.value,
        subscription: sessionId.value || undefined,
      })
    } catch (e: any) {
      ElMessage.error(e?.message || 'send command failed')
    }
    return
  }

  try {
    await client.sendUserMessage({
      content: text,
      receiverId: agentId.value,
      subscription: sessionId.value || undefined,
    })
  } catch (e: any) {
    ElMessage.error(e?.message || 'send failed')
  }
}

const respondPermission = async (granted: boolean) => {
  if (!client) return
  try {
    await client.sendPermissionResponse({
      granted,
      requestId: permissionDialog.requestId,
      receiverId: permissionDialog.senderId,
      subscription: sessionId.value || undefined,
    })
  } catch (e: any) {
    ElMessage.error(e?.message || 'permission response failed')
  } finally {
    permissionDialog.visible = false
  }
}

onMounted(async () => {
  await userStore.init()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- Top status bar -->
    <div class="sticky top-0 z-10 bg-white border-b">
      <div class="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="font-semibold text-gray-900">Broca Web</div>
          <el-tag :type="connected ? 'success' : connecting ? 'warning' : 'info'">{{ statusText }}</el-tag>
          <div class="text-xs text-gray-500">client_id: {{ socketConfig.clientId }}</div>
        </div>
        <div class="flex items-center gap-2">
          <el-input v-model="socketConfig.serverUrl" size="small" style="width: 220px" placeholder="socketio url" />
          <el-button size="small" type="primary" :loading="connecting" @click="doConnect">Connect</el-button>
        </div>
      </div>
    </div>

    <div class="mx-auto max-w-6xl px-4 py-6 grid grid-cols-12 gap-4">
      <!-- Left: session/control panel -->
      <div class="col-span-12 lg:col-span-3">
        <div class="bg-white rounded-lg border p-4 space-y-3">
          <div class="text-sm font-semibold text-gray-900">Session</div>
          <el-input v-model="sessionId" placeholder="session_id" />
          <el-input v-model="agentId" placeholder="agent_id" />
          <div class="flex gap-2">
            <el-button type="primary" plain @click="doSubscribe">Subscribe</el-button>
            <el-button plain @click="uiMessages = []">Clear</el-button>
          </div>
          <div class="text-xs text-gray-500 leading-5">
            Commands: <code>/help</code> <code>/status</code> <code>/abort</code> <code>/clear</code>
          </div>
        </div>

        <div class="mt-4 bg-white rounded-lg border p-4">
          <div class="text-sm font-semibold text-gray-900 mb-2">Event Stats</div>
          <div class="text-xs text-gray-600">messages: {{ uiMessages.length }}</div>
        </div>
      </div>

      <!-- Middle: message list -->
      <div class="col-span-12 lg:col-span-6">
        <div class="bg-white rounded-lg border h-[70vh] overflow-auto p-3 space-y-2">
          <div v-if="!uiMessages.length" class="text-sm text-gray-500 py-10 text-center">
            No messages yet. Connect and subscribe.
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
          />
          <el-button type="primary" @click="send">Send</el-button>
        </div>
      </div>

      <!-- Right: detail inspector -->
      <div class="col-span-12 lg:col-span-3">
        <div class="bg-white rounded-lg border p-4">
          <div class="text-sm font-semibold text-gray-900 mb-2">Details</div>
          <div class="text-xs text-gray-600">
            选中消息的 JSON 详情（待实现：点击列表项设置 selected）。
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
