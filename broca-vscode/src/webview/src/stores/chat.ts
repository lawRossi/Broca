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

  // Initialize: listen for messages from extension host
  function init() {
    onMessage((data: any) => {
      switch (data.type) {
        case 'connected':
          connected.value = data.payload.connected
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
    // Deduplicate: skip if we already have this message_id (from optimistic update or echo)
    if (messages.value.some(m => m.message_id === message.message_id)) return

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

    // Filter out internal messages
    const filteredTypes = [
      'turn_start', 'turn_end', 'command',
      'subscribe', 'unsubscribe', 'connect', 'disconnect',
      'ping', 'pong',
    ]
    if (filteredTypes.includes(message.message_type)) return

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

    // Add message to list
    addMessage(message)
  }

  function handleHistoryLoaded(payload: {
    messages: Message[]
    total: number
    skip: number
    limit: number
  }) {
    if (payload.skip === 0) {
      // Initial load - replace all messages
      messages.value = payload.messages || []
    } else {
      // Load more - prepend to existing messages
      const newMessages = [...(payload.messages || []), ...messages.value]
      messages.value = newMessages
    }

    historySkip.value = payload.skip + payload.limit
    historyTotal.value = payload.total
    hasMoreHistory.value = historySkip.value < historyTotal.value
    loading.value = false
    loadingMore.value = false
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
        return
      }
    }

    // Handle agent_response chunk merging
    if (message.message_type === 'agent_response') {
      const existingIndex = messages.value.findIndex(
        (m) => m.message_type === 'agent_response' && m.message_id === message.message_id
      )
      if (existingIndex !== -1) {
        // Merge chunks
        const existing = messages.value[existingIndex]
        const existingContent = existing.data?.content ? JSON.parse(existing.data.content) : {}
        const newContent = message.data?.content ? JSON.parse(message.data.content) : {}

        messages.value[existingIndex] = {
          ...existing,
          data: {
            ...existing.data,
            content: JSON.stringify({
              content: (existingContent.content || '') + (newContent.content || ''),
              reasoning_content: (existingContent.reasoning_content || '') + (newContent.reasoning_content || ''),
            }),
          },
          timestamp: message.timestamp,
        }
        return
      }
    }

    messages.value.push(message)
  }

  function sendMessage(content: string, receiverId?: string, files?: any[]) {
    if (!content.trim() && (!files || files.length === 0)) return

    // Generate messageId for optimistic update AND to share with extension
    const messageId = `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`
    
    // Optimistic update - add user message locally
    addMessage({
      message_id: messageId,
      message_type: 'user_message',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: 'user',
      receiver_id: receiverId,
      subscription: sessionId.value,
      data: { content, ...(files && { files }) },
    })

    // Send to extension host (include messageId so echo can be deduplicated)
    postMessage({
      type: 'sendMessage',
      payload: { content, receiverId, files, messageId },
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

  function sendUndo(targetMessageId?: string, level: 'turn' | 'step' = 'step') {
    postMessage({
      type: 'undo',
      payload: { targetMessageId, level },
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
    runnerAlive,
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
