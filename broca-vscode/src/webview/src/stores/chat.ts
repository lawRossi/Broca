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
    console.log('[ChatStore] init, sessionId:', sessionId.value, 'connected:', connected.value)
    
    onMessage((data: any) => {
      console.log('[ChatStore] received from extension:', data.type)
      switch (data.type) {
        case 'connected':
          connected.value = data.payload.connected
          break

        case 'agents':
          defaultAgentId.value = data.payload.defaultAgentId
          // Build agent name map
          const names: Record<string, string> = {}
          for (const agent of data.payload.agents || []) {
            names[agent.agent_id] = agent.name || agent.agent_id
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
    // TEMP: push everything except internal types
    const skip = ['turn_start', 'turn_end', 'command', 'subscribe', 'unsubscribe', 'connect', 'disconnect', 'ping', 'pong']
    if (skip.includes(message.message_type)) return

    // Debug: log ALL incoming messages  
    console.log('[ChatStore] GOT MESSAGE:', message.message_type, message.message_id, message.data?.content?.substring?.(0, 60))

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

    // Clear redo state
    if (message.message_type !== 'command_result') {
      showRedoButton.value = false
      redoReceiverId.value = undefined
    }

    // Permission dialog
    if (message.message_type === 'permission_request') {
      permissionDialog.value = { visible: true, requestId: message.data?.request_id, senderId: message.sender_id, message: message.data?.message || 'Permission required' }
      return
    }

    // Agent query dialog
    if (message.message_type === 'agent_query') {
      agentQueryDialog.value = { visible: true, requestId: message.data?.request_id, senderId: message.sender_id, question: message.data?.question || message.data?.content || '', options: message.data?.options || [] }
      return
    }

    // Add message directly (NO filtering, NO merging)
    messages.value.push(message)
    console.log('[ChatStore] Messages count now:', messages.value.length)
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
    // Filter history messages through processMessage (remove empties, internal, etc.)
    const filtered = (payload.messages || []).filter(m => processMessage(m) !== null)

    if (payload.skip === 0) {
      // Initial load: merge with any messages already received in real-time
      // (don't replace, otherwise real-time messages arriving before history load complete get lost)
      const existingIds = new Set(messages.value.map(m => m.message_id))
      const newFromHistory = filtered.filter(m => !existingIds.has(m.message_id))
      // Keep existing messages first (they arrived in real-time), append history messages that aren't already there
      messages.value = [...messages.value, ...newFromHistory]
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
        console.log('[ChatStore] Merging agent_response chunk, existing index:', existingIndex)
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
        console.log('[ChatStore] Merged content length:', (existingContent.content || '').length + (newContent.content || '').length)
        return
      } else {
        console.log('[ChatStore] First agent_response chunk, pushing new message')
      }
    }

    messages.value.push(message)
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
    addMessage({
      message_id: messageId,
      message_type: 'user_message',
      timestamp: new Date().toISOString(),
      role: 'user',
      sender_id: 'user',
      receiver_id: targetReceiver,
      data: { content, ...(files && { files }) },
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
