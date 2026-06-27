<script setup lang="ts">
import { useChatStore, useAgentStore, useSocketStore } from '@/stores'
import type { Message } from '@/api/brocaSocket'
import { formatBeijingTimeShort } from '@/utils/time'
import { marked } from 'marked'
import { ref, computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import FilePreview from './FilePreview.vue'
import { diffLines } from 'diff'
import { renderMarkdown } from '@/utils/markdown'

const chatStore = useChatStore()
const agentStore = useAgentStore()
const socketStore = useSocketStore()

// 文件预览状态
const showFilePreview = ref(false)
const previewFilePath = ref<string>('')
const previewFileUrl = ref<string>('')

// 显示/隐藏撤销按钮
const showActions = ref(false)

// 折叠状态：用户输入超过 300 字符
const showFullUserMessage = ref(false)
const MAX_USER_CHARS = 300
const isLongUserMessage = computed(() => {
  if (props.message.message_type !== 'user_message' && props.message.role !== 'user') return false
  const content = getContent(props.message)
  if (!content) return false
  return String(content).length > MAX_USER_CHARS
})

const props = defineProps<{
  message: Message
}>()

const getIcon = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return '👤'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return '🤖'
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return '⚠️'
  } else if (message.message_type === 'tool_call') {
    // 根据工具调用状态显示不同的图标
    const status = message.data?.status
    const hasResult = message.data?.result !== undefined

    if (!hasResult) {
      // 工具调用进行中
      return '🔧⏳'
    } else if (status === true || status === 'success') {
      // 工具调用成功完成
      return '🔧✅'
    } else if (status === false || status === 'error') {
      // 工具调用失败
      return '🔧❌'
    } else {
      return '🔧'
    }
  }
  return '💬'
}

const getSenderName = (message: Message, agentName: string) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    const targetAgentId = message.receiver_id || message.agent_id
    if (targetAgentId && targetAgentId !== agentStore.currentAgentId) {
      const targetAgent = agentStore.agents.find((a) => a.agent_id === targetAgentId)
      const targetName = targetAgent?.name || targetAgentId
      return `You → @${targetName}`
    }
    return 'You'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    const senderAgentId = message.sender_id || message.agent_id
    if (senderAgentId && senderAgentId !== agentStore.currentAgentId) {
      const senderAgent = agentStore.agents.find((a) => a.agent_id === senderAgentId)
      const senderName = senderAgent?.name || senderAgentId
      return `@${senderName}`
    }
    return agentName
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return 'Error'
  } else if (message.message_type === 'tool_call') {
    const senderAgentId = message.sender_id || message.agent_id
    if (senderAgentId && senderAgentId !== agentStore.currentAgentId) {
      const senderAgent = agentStore.agents.find((a) => a.agent_id === senderAgentId)
      const senderName = senderAgent?.name || senderAgentId
      return `@${senderName} - Tool`
    }
    return ''
  } else if (message.message_type === 'agent_system_message' || message.role === 'agent_system') {
    return 'System'
  }
  return 'Unknown'
}

const getHeaderColor = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return 'text-gray-500'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return 'text-blue-600'
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return 'text-red-600'
  } else if (message.message_type === 'tool_call') {
    return 'text-amber-700'
  }
  return 'text-gray-500'
}

const getBgClass = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return 'msg-user'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return 'msg-agent'
  } else if (message.message_type === 'agent_system_message' || message.role === 'agent_system') {
    return 'msg-system'
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return 'msg-error'
  } else if (message.message_type === 'tool_call') {
    return 'msg-tool'
  }
  return ''
}

const getContentClass = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return ''
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return ''
  } else if (message.message_type === 'agent_system_message' || message.role === 'agent_system') {
    return 'font-mono'
  } else if (message.message_type === 'tool_call') {
    return ''
  }
  return ''
}

const getContent = (message: Message) => {
  if (message.message_type === 'tool_call') {
    return message.data?.tool_name || 'unknown_tool'
  }

  // command_result 消息内容在 data.result 中（可能是 { code, message } 对象或纯字符串）
  if (message.message_type === 'command_result') {
    const result = message.data?.result
    if (typeof result === 'object' && result !== null) {
      return result.message || result.value || JSON.stringify(result)
    }
    return result || message.data?.message || ''
  }

  if (message.data?.raw_input !== undefined) {
    return message.data.raw_input
  }

  const content = message.data?.content || message.data?.message || ''

  // 尝试解析 JSON 格式的 content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      if (parsed && typeof parsed === 'object' && parsed.content !== undefined) {
        // 如果是数组
        if (Array.isArray(parsed.content)) {
          //获取type为text的部份
          const textParts = parsed.content.filter((part: any) => part.type === 'text')
          return textParts.map((part: any) => part.text).join('')
        } else {
          return parsed.content
        }
      }
      return JSON.stringify(parsed, null, 2)
    } catch (e) {
      // 如果不是有效的 JSON，返回原始字符串
      return content
    }
  }

  // 如果 content 不是字符串，直接返回
  return content
}

const isFileManagementTool = (message: Message) => {
  return message.message_type === 'tool_call' && (message.data?.tool_name === 'read_file' || message.data?.tool_name === 'write_file' || message.data?.tool_name === 'edit_file')
}

const getFilePath = (message: Message) => {
  const params = JSON.parse(message.data?.arguments || '{}')
  return params.path
}

// 检查是否为edit_file工具调用
const isEditFile = (message: Message) => {
  return message.message_type === 'tool_call' && message.data?.tool_name === 'edit_file'
}

// 计算两个文本之间的 diff
interface DiffLine {
  type: 'added' | 'removed' | 'unchanged'
  content: string
}

const computeDiff = (oldText: string, newText: string): DiffLine[] => {
  const result: DiffLine[] = []
  
  // 使用 diff 库计算差异
  const diffResult = diffLines(oldText || '', newText || '')
  
  diffResult.forEach((part) => {
    const lines = part.value.split('\n')
    // 移除最后一个空行（split会在末尾产生空字符串）
    if (lines.length > 0 && lines[lines.length - 1] === '') {
      lines.pop()
    }
    
    lines.forEach((line) => {
      if (part.added) {
        result.push({ 
          type: 'added', 
          content: line
        })
      } else if (part.removed) {
        result.push({ 
          type: 'removed', 
          content: line
        })
      } else {
        result.push({ 
          type: 'unchanged', 
          content: line
        })
      }
    })
  })
  
  return result
}

// 获取 edit_file 的参数
const getEditFileParams = (message: Message) => {
  if (!isEditFile(message)) return null
  
  const args = message.data?.arguments
  if (!args) return null
  
  const params = typeof args === 'string' ? JSON.parse(args) : args
  
  return {
    path: params.path || '',
    oldText: params.old_text || '',
    newText: params.new_text || '',
    encoding: params.encoding || 'utf-8',
    newFile: params.new_file || false
  }
}

const getWriteFileContent = (message: Message) => {
  const params = JSON.parse(message.data.arguments)
  return params.content?.trim()
}

// 检查是否为todo_management工具调用
const isTodoManagement = (message: Message) => {
  return message.message_type === 'tool_call' && message.data?.tool_name === 'todo_management'
}

// 检查是否为ask_user工具调用
const isAskUser = (message: Message) => {
  return message.message_type === 'tool_call' && message.data?.tool_name === 'ask_user'
}

const isReadFile = (message: Message) =>{
  return message.message_type === 'tool_call' && message.data?.tool_name === 'read_file'
}

const isWriteFile = (message: Message) => {
  return message.message_type === 'tool_call' && message.data?.tool_name === 'write_file'
}

// 获取todos列表
const getTodos = (message: Message) => {
  if (!isTodoManagement(message)) return null

  const argumentsData = message.data?.arguments || message.data?.parameters
  if (!argumentsData) return null

  if (typeof argumentsData !== 'object') {
    const parsed = JSON.parse(argumentsData)
    return parsed.todos || null
  }

  return argumentsData.todos || null
}

// 解析ask_user参数
const getAskUserParams = (message: Message) => {
  if (!isAskUser(message)) return null

  const args = message.data?.arguments || message.data?.parameters
  if (!args) return null

  return typeof args === 'string' ? JSON.parse(args) : args
}

// 解析ask_user结果
const getAskUserResult = (message: Message) => {
  if (!isAskUser(message)) return null
  return message.data?.result
}

// 判断参数是否应该展开（默认展开）
const shouldExpandParameters = (message: Message) => {
  if (isTodoManagement(message) || isAskUser(message)) {
    return true
  }
  return getShowParameters(message.message_id)
}

const getParametersTitle = (message: Message) => {
  if (isEditFile(message)) {
    return '编辑内容'
  }
  else if (isWriteFile(message)) {
    return '文件内容'
  }
  return '参数'
}

// 判断结果是否应该展开（默认展开）
const shouldExpandResult = (message: Message) => {
  if (isAskUser(message)) {
    return true
  }
  return getShowResult(message.message_id)
}

const getResultTitle = (message: Message) => {
  if (isAskUser(message)) {
    return '回答'
  }
  else if (isReadFile(message)) {
    return '文件内容'
  }
  return '结果'
}

const shouldShowResult = (message: Message) => {
  const exceptions = ['todo_management', 'edit_file', 'write_file']
  return message.message_type === 'tool_call' && !exceptions.includes(message.data?.tool_name)
}

const shouldShowParameters = (message: Message) => {
  const exceptions = ['read_file']
  return message.message_type === 'tool_call' && !exceptions.includes(message.data?.tool_name)
}

const getShowParameters = (messageId: string) => {
  return chatStore.messageStates.get(messageId)?.showParameters || false
}

const getShowResult = (messageId: string) => {
  return chatStore.messageStates.get(messageId)?.showResult || false
}

const getShowReasoning = (messageId: string) => {
  return chatStore.messageStates.get(messageId)?.showReasoning || false
}

const getReasoningContentFromData = (message: Message): string => {
  const content = message.data?.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.reasoning_content || ''
    } catch {
      return ''
    }
  }
  return ''
}

const hasReasoningContent = (message: Message) => {
  return !!getReasoningContentFromData(message)
}

const getReasoningContent = (message: Message) => {
  return getReasoningContentFromData(message)
}

// 获取格式化的JSON字符串
const getFormattedJson = (data: any): string => {
  if (data === null || data === undefined) {
    return 'null'
  }
  
  try {
    // 如果已经是字符串，尝试解析为JSON再格式化
    if (typeof data === 'string') {
      try {
        const parsed = JSON.parse(data)
        return JSON.stringify(parsed, null, 2)
      } catch {
        // 如果不是有效的JSON，返回原始字符串
        return data
      }
    }

    // 如果是对象或数组，直接格式化
    if (typeof data === 'object' || Array.isArray(data)) {
      return JSON.stringify(data, null, 2)
    }
    // 其他类型（数字、布尔值等）直接转换为字符串
    return String(data)
  } catch (e) {
    // 如果解析失败，返回原始字符串
    return String(data)
  }
}


// 打开文件预览
const openFilePreview = (file: { url?: string; path?: string; name?: string; type?: string }) => {
  // 优先使用 url（Supabase Storage），否则使用 path（本地文件）
  if (file.url) {
    previewFilePath.value = '' // 清空 path
    previewFileUrl.value = file.url
  } else if (file.path) {
    previewFileUrl.value = '' // 清空 url
    previewFilePath.value = file.path
  }
  showFilePreview.value = true
}

// 获取文件图标
const getFileIcon = (fileType?: string, fileName?: string): string => {
  const type = fileType?.toLowerCase() || ''
  const name = fileName?.toLowerCase() || ''

  if (type.startsWith('image/') || /\.(jpg|jpeg|png|gif|bmp|svg|webp)$/.test(name)) {
    return '🖼️'
  }
  if (type.startsWith('video/') || /\.(mp4|mov|avi|wmv|flv|mkv)$/.test(name)) {
    return '📹'
  }
  if (type.startsWith('audio/') || /\.(mp3|wav|ogg|m4a)$/.test(name)) {
    return '🎵'
  }
  if (type.includes('pdf') || /\.pdf$/.test(name)) {
    return '📄'
  }
  if (type.includes('word') || type.includes('document') || /\.(doc|docx)$/.test(name)) {
    return '📝'
  }
  if (type.includes('excel') || type.includes('spreadsheet') || /\.(xls|xlsx|csv)$/.test(name)) {
    return '📊'
  }
  if (type.includes('text/') || /\.(txt|md|json|xml|html|css|js|ts)$/.test(name)) {
    return '📃'
  }
  if (type.includes('zip') || type.includes('compressed') || /\.(zip|rar|7z|tar|gz)$/.test(name)) {
    return '📦'
  }
  return '📎'
}

// 格式化文件大小
const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

// ==================== 撤销功能相关 ====================

// 判断消息是否可撤销
const canUndoThisMessage = computed(() => {
  // 基本条件检查
  if (!chatStore.connected || !chatStore.sessionId || !chatStore.runnerAlive) {
    return false
  }
  
  // 支持撤销的消息类型
  const undoableTypes = ['user_message', 'tool_call', 'agent_response']
  if (!undoableTypes.includes(props.message.message_type)) {
    return false
  }

  return true
})

// 获取撤销级别
const getUndoLevel = computed(() => {
  if (props.message.message_type === 'user_message') {
    return 'turn'
  } else {
    return 'step'
  }
})

// 确认撤销
const confirmUndo = () => {
  let messageText = '确定要撤销此操作吗？'
  
  ElMessageBox.confirm(messageText, '确认撤销', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    handleUndoToHere()
  }).catch(() => {
    // 用户取消
  })
}

// 执行撤销
const handleUndoToHere = async () => {
  if (!canUndoThisMessage.value) return
    
  let targetAgentId = null
  const message = props.message
  if (message.message_type === 'user_message') {
    targetAgentId = message.receiver_id || message.agent_id
  } else {
    targetAgentId = message.agent_id || message.sender_id
  }

  try {
    await socketStore.sendUndo({
      targetMessageId: props.message.message_id,
      level: getUndoLevel.value,
      subscription: chatStore.sessionId,
      receiverId: targetAgentId
    })
  } catch (error) {
    console.error('撤销失败:', error)
  }
}
</script>

<template>
  <div 
    class="message-container"
    :class="getBgClass(message)"
    @mouseenter="showActions = true"
    @mouseleave="showActions = false"
  >
    <div
      v-if="message.message_type !== 'system_message' && message.role !== 'system'"
      class="flex items-center justify-between gap-2 mb-2"
    >
      <div class="flex items-center gap-2">
        <span class="text-lg">{{ getIcon(message) }}</span>
        <span class="font-semibold text-sm sender-name" :class="getHeaderColor(message)">
          {{ getSenderName(message, agentStore.currentAgentName) }}
        </span>
      </div>
      
      <div class="flex items-center gap-2">
        <div class="text-xs text-gray-500">
          {{ formatBeijingTimeShort(message.timestamp) }}
        </div>
        
        <!-- 悬停撤销按钮（编排会话禁用） -->
        <div class="hover-actions" v-if="showActions && canUndoThisMessage && !chatStore.isAgentOrchestration">
          <el-button 
            size="small" 
            link
            @click.stop="confirmUndo"
            title="撤销此操作"
            class="!p-1 !min-h-0 !h-auto undo-button"
          >
            <span class="text-xs">↩️ 撤销</span>
          </el-button>
        </div>
      </div>
    </div>

    <div>
      <div v-if="message.message_type === 'agent_response' && hasReasoningContent(message)" class="mb-2">
        <el-button
          size="small"
          type="default"
          class="!text-amber-700 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
          @click="chatStore.toggleReasoning(message.message_id)"
        >
          <span class="flex items-center gap-1">
            <span>{{ getShowReasoning(message.message_id) ? '▼' : '▶' }}</span>
            <span class="text-xs">思考</span>
          </span>
        </el-button>

        <div
          v-if="getShowReasoning(message.message_id)"
          class="reasoning-content"
        >
          <pre class="reasoning-text">{{ getReasoningContent(message) }}</pre>
        </div>
      </div>

      <!-- 用户消息：内容 + 文件附件 -->
      <template v-if="message.message_type === 'user_message' || message.role === 'user'">
        <!-- 用户消息使用普通文本渲染，不使用 markdown -->
        <div class="user-msg-wrapper">
          <pre
            class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-0"
            :class="[getContentClass(message), { 'user-msg-collapsed': isLongUserMessage && !showFullUserMessage }]"
          >{{ getContent(message) }}</pre>
          <button
            v-if="isLongUserMessage"
            class="user-msg-expand-btn"
            @click="showFullUserMessage = !showFullUserMessage"
          >
            {{ showFullUserMessage ? '收起 ▲' : '展开 ▼' }}
          </button>
        </div>

        <!-- 文件附件显示 -->
        <div v-if="message.data?.files && message.data.files.length > 0" class="mt-2 space-y-2">
          <div
            v-for="(file, index) in message.data.files"
            :key="index"
            class="flex items-center gap-3 p-2 bg-white border rounded-lg hover:bg-gray-50 cursor-pointer transition-colors"
            @click="openFilePreview(file)"
          >
            <!-- 文件图标 -->
            <span class="text-2xl">{{ getFileIcon(file.type, file.name) }}</span>

            <!-- 文件信息 -->
            <div class="flex-1 min-w-0">
              <div class="font-medium text-sm text-gray-800 truncate">{{ file.name }}</div>
              <div class="text-xs text-gray-500">
                {{ formatFileSize(file.size) }}
                <span v-if="file.type" class="ml-1">• {{ file.type }}</span>
              </div>
            </div>

            <!-- 预览图标 -->
            <span class="text-gray-400 hover:text-blue-500">👁️</span>
          </div>
        </div>
      </template>

      <!-- agent_response 使用 markdown 渲染 -->
      <div
        v-else-if="message.message_type === 'agent_response' || message.role === 'assistant'"
        class="markdown-content text-xs sm:text-sm leading-relaxed mb-2 overflow-x-auto"
        :class="getContentClass(message)"
        v-html="renderMarkdown(getContent(message))"
      ></div>

      <!-- command_result 使用 markdown 渲染（如 /help 输出的标题、列表等） -->
      <div
        v-else-if="message.message_type === 'command_result'"
        class="markdown-content text-xs sm:text-sm leading-relaxed mb-2 overflow-x-auto"
        v-html="renderMarkdown(getContent(message))"
      ></div>

      <!-- 其他消息类型 -->
      <pre
        v-else
        class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-2"
        :class="getContentClass(message)"
        >{{ getContent(message) }}</pre
      >

      <div v-if="message.message_type === 'tool_call'" class="mt-2">
        <div v-if="isFileManagementTool(message)" class="diff-header px-3 py-2 border-b flex items-center gap-2">
          <span class="diff-path font-medium text-sm" :title="getFilePath(message)"> 📃 {{ getFilePath(message)}} </span>
        </div>

        <!-- 参数展示 -->
        <div v-if="shouldShowParameters(message)" class="mb-2">
          <!-- 只有非todo_management且非ask_user且非edit_file工具才显示切换按钮 -->
          <el-button
            v-if="!isTodoManagement(message) && !isAskUser(message)"
            size="small"
            type="default"
            class="tool-label-btn"
            @click="chatStore.toggleToolParameters(message.message_id)"
          >
            {{ getParametersTitle(message) }}
          </el-button>

          <!-- 参数内容：特殊处理todo_management和ask_user -->
          <div v-if="shouldExpandParameters(message)" class="params-container mt-1 p-2 rounded border">
            <div v-if="isAskUser(message)" class="tool-label text-xs font-semibold mb-1">问题:</div>

            <!-- 特殊处理todo_management的todos列表 -->
            <div v-if="isTodoManagement(message) && getTodos(message)" class="params-inner p-2 rounded border">
              <div v-for="(todo, index) in getTodos(message)" :key="index" class="mb-2 last:mb-0">
                <div class="flex items-start gap-2">
                  <span class="mt-1 text-sm">
                    <span v-if="todo.status === 'completed'">✅</span>
                    <span v-else-if="todo.status === 'in_progress'">⏳</span>
                    <span v-else>⬜️</span>
                  </span>
                  <div class="flex-1">
                    <div class="params-todo-name text-sm font-medium">
                      {{ todo.name }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 特殊处理ask_user的参数 -->
            <div v-else-if="isAskUser(message) && getAskUserParams(message)" class="params-inner p-3 rounded border">
              <div class="params-question text-sm font-medium mb-2">
                {{ getAskUserParams(message).question }}
              </div>
              <div v-if="getAskUserParams(message).options?.length" class="space-y-1 ml-2">
                <div
                  v-for="(opt, optIndex) in getAskUserParams(message).options"
                  :key="optIndex"
                  class="params-option text-xs flex items-start gap-1"
                >
                  <span class="params-bullet">•</span>
                  <span>{{ opt.name }}</span>
                  <span v-if="opt.description" class="params-desc">- {{ opt.description }}</span>
                </div>
              </div>
            </div>

            <!-- 特殊处理edit_file的diff展示 -->
            <div v-else-if="isEditFile(message) && getEditFileParams(message)" class="diff-wrapper rounded border overflow-hidden">
              <!-- Diff 展示 -->
              <div v-if="getEditFileParams(message).oldText || getEditFileParams(message).newText" class="diff-container font-mono text-xs">
                <div 
                  v-for="(line, index) in computeDiff(getEditFileParams(message).oldText, getEditFileParams(message).newText)" 
                  :key="index"
                  class="diff-line"
                  :class="{
                    'diff-added': line.type === 'added',
                    'diff-removed': line.type === 'removed',
                    'diff-unchanged': line.type === 'unchanged'
                  }"
                >
                  {{ line.content }}
                </div>
              </div>
              
              <!-- 如果没有old_text和new_text，显示格式化的JSON -->
              <div v-else class="p-3">
                <pre class="json-display text-xs font-mono whitespace-pre-wrap break-words overflow-auto max-h-96" v-html="getFormattedJson(message.data.arguments || message.data.parameters)"></pre>
              </div>
            </div>

            <!--file_write-->
            <pre v-else-if="isWriteFile(message)" class="file-content text-xs font-mono whitespace-pre-wrap break-words p-2 rounded border overflow-auto max-h-96">
              {{ getWriteFileContent(message) }}
            </pre>

            <!-- 其他工具显示参数 -->
            <pre
              v-else
              class="json-display text-xs font-mono text-purple-800 whitespace-pre-wrap break-words bg-white p-2 rounded border overflow-auto max-h-96"
              v-html="getFormattedJson(message.data.arguments || message.data.parameters)"
            ></pre
            >
          </div>
        </div>

        <!--结果展示-->
        <div v-if="message.data?.result !== undefined && shouldShowResult(message)" class="mb-2">
          <el-button
            v-if="!isAskUser(message)"
            size="small"
            type="default"
            class="tool-label-btn"
            @click="chatStore.toggleToolResult(message.message_id)"
          >
            {{ getResultTitle(message) }}
          </el-button>

          <!-- ask_user结果默认展开 -->
          <div v-if="shouldExpandResult(message)" class="result-container mt-1 p-2 rounded border">
            <div v-if="isAskUser(message)" class="tool-label text-xs font-semibold mb-1">回答:</div>

            <!-- 特殊处理ask_user结果 -->
            <div v-if="isAskUser(message) && getAskUserResult(message)" class="result-inner p-2 rounded border">
              <div class="result-text text-sm">
                {{ getAskUserResult(message) }}
              </div>
            </div>

            <!-- 其他工具显示结果 -->
            <pre
              v-else
              class="result-pre text-xs font-mono whitespace-pre-wrap break-words p-2 rounded border overflow-auto max-h-96"
            >{{message.data.result}}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 文件预览组件 -->
  <FilePreview
    v-model:visible="showFilePreview"
    :file-path="previewFilePath"
    :file-url="previewFileUrl"
    @close="showFilePreview = false"
  />
</template>
<style scoped>
/* ==================== 消息容器 ==================== */
.message-container {
  position: relative;
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 6px;
  font-size: 13px;
  line-height: 1.5;
  transition: all 0.2s ease;
}

.message-container:hover {
  background: rgba(0, 0, 0, 0.02);
}

/* ==================== 消息类型样式 ==================== */
.msg-user {
  border-left: 4px solid var(--text-secondary, #8e8e8e);
  margin-left: 8px;
  color: var(--text-primary, #334155);
}

.msg-agent {
  border-left: 4px solid #5a8fc9;
  margin-right: 8px;
  color: var(--text-primary, #334155);
}

.msg-tool {
  border-left: 4px solid #c9a84c;
  font-size: 12px;
  color: var(--text-primary, #334155);
}

.msg-system {
  text-align: center;
  border: 1px solid var(--border-color, #e0e0e0);
}

.msg-error {
  border-left: 4px solid #c95a5a;
  color: var(--error-fg, #c95a5a);
}

/* 发送者名字 */
.sender-name {
  font-weight: 600;
  font-size: 12px;
}

.msg-user .sender-name {
  color: var(--text-secondary, #8e8e8e);
}

/* ==================== 悬停操作 ==================== */
.hover-actions {
  opacity: 0;
  transition: opacity 0.2s ease;
}

.message-container:hover .hover-actions {
  opacity: 1;
}

.hover-actions .el-button.undo-button {
  color: #f56c6c;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(245, 108, 108, 0.1);
  border: 1px solid rgba(245, 108, 108, 0.2);
}

.hover-actions .el-button.undo-button:hover {
  background: rgba(245, 108, 108, 0.2);
  color: #f56c6c;
  border-color: rgba(245, 108, 108, 0.3);
}

/* ==================== 推理内容 ==================== */
.reasoning-content {
  margin-top: 6px;
  padding: 8px 12px;
  border-left: 3px solid var(--warning-fg, #d97706);
  border-radius: 4px;
}

.reasoning-text {
  margin: 0;
  font-family: var(--code-font-family, 'Consolas', 'Courier New', monospace);
  font-size: 11px;
  color: var(--warning-fg, #b89500);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

/* ==================== 工具标签按钮 ==================== */
.tool-label-btn {
  font-size: 12px !important;
  color: #b45309 !important;
  padding: 0 !important;
  height: auto !important;
  min-height: 0 !important;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  font-weight: 500;
}

.tool-label-btn:hover {
  color: #92400e !important;
  background: transparent !important;
}

.tool-label {
  color: var(--warning-fg, #c9a84c);
}

.params-question {
  color: var(--text-primary, #333);
}

.params-option {
  color: var(--text-primary, #333);
  font-size: 12px;
}

.params-bullet {
  color: var(--warning-fg, #c9a84c);
}

.params-desc {
  color: var(--text-secondary, #808080);
}

/* ==================== 工具调用区域 ==================== */
.diff-header {
  padding: 6px 10px;
  background: var(--bg-tertiary, #f1f5f9);
  border-bottom: 1px solid var(--border-color, #e0e0e0);
  font-size: 12px;
  overflow: hidden;
}

.diff-path {
  color: var(--text-link, #3b82f6);
  font-weight: 500;
  font-family: var(--code-font-family, 'Consolas', monospace);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  min-width: 0;
}

.params-container {
  border-color: rgba(201, 168, 76, 0.25);
  background: rgba(201, 168, 76, 0.06);
}

.params-inner {
  border-color: var(--border-color, #e0e0e0);
  background: #fff;
}

.params-todo-name {
  font-size: 12px;
  font-weight: 500;
}

/* ==================== Diff 展示 ==================== */
.diff-wrapper {
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 4px;
  overflow: hidden;
  background: #fff;
}

.diff-container {
  max-height: 400px;
  overflow-y: auto;
  overflow-x: auto;
}

.diff-line {
  display: block;
  white-space: pre;
  padding: 1px 0 1px 28px;
  position: relative;
  min-height: 22px;
  line-height: 22px;
  width: fit-content;
  min-width: 100%;
  font-family: var(--code-font-family, 'Consolas', monospace);
  font-size: 11px;
}

.diff-line::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 24px;
  text-align: center;
  font-weight: 700;
  line-height: 22px;
}

.diff-added {
  background-color: rgba(0, 200, 80, 0.15);
}

.diff-added::before {
  content: '+';
  color: #16a34a;
}

.diff-removed {
  background-color: rgba(200, 0, 0, 0.15);
}

.diff-removed::before {
  content: '-';
  color: #dc2626;
}

.diff-unchanged {
  background-color: transparent;
}

.diff-unchanged::before {
  content: '';
}

.diff-line:hover {
  filter: brightness(1.05);
}

.diff-added:hover {
  background-color: rgba(0, 200, 80, 0.2);
}

.diff-removed:hover {
  background-color: rgba(200, 0, 0, 0.2);
}

/* ==================== 结果展示 ==================== */
.result-container {
  border-color: rgba(201, 168, 76, 0.25);
  background: rgba(201, 168, 76, 0.06);
}

.result-inner {
  border-color: var(--border-color, #e0e0e0);
  background: #fff;
}

.result-text {
  color: var(--text-primary, #333);
}

.result-pre {
  font-family: var(--code-font-family, 'Consolas', monospace);
  font-size: 11px;
  color: var(--text-primary, #333);
  border-color: var(--border-color, #e0e0e0);
  background: #fff;
}

/* ==================== 文件内容展示 ==================== */
.file-content {
  background: var(--bg-tertiary, #f1f5f9);
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 4px;
  font-family: var(--code-font-family, 'Consolas', monospace);
  font-size: 11px;
  color: var(--text-primary, #333);
}

/* ==================== JSON 显示 ==================== */
.json-display {
  font-family: var(--code-font-family, 'Consolas', monospace);
  line-height: 1.4;
}

/* ==================== Markdown 样式 ==================== */
:deep(.markdown-content) {
  word-wrap: break-word;
  overflow-wrap: break-word;
  color: var(--text-primary, #333);
  font-size: 13px;
  line-height: 1.6;
}

:deep(.markdown-content h1),
:deep(.markdown-content h2),
:deep(.markdown-content h3),
:deep(.markdown-content h4),
:deep(.markdown-content h5),
:deep(.markdown-content h6) {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.25;
  color: #1e293b;
}

:deep(.markdown-content h1) { font-size: 1.5em; border-bottom: 1px solid var(--border-color, #eaecef); padding-bottom: 0.3em; }
:deep(.markdown-content h2) { font-size: 1.3em; border-bottom: 1px solid var(--border-color, #eaecef); padding-bottom: 0.3em; }
:deep(.markdown-content h3) { font-size: 1.1em; }
:deep(.markdown-content p) { margin-bottom: 1em; line-height: 1.6; }
:deep(.markdown-content ul),
:deep(.markdown-content ol) { padding-left: 2em; margin-bottom: 1em; }
:deep(.markdown-content li) { margin-bottom: 0.25em; }
:deep(.markdown-content blockquote) {
  margin: 1em 0;
  padding: 0.5em 1em;
  color: var(--text-secondary, #6a737d);
  border-left: 0.25em solid var(--border-color, #dfe2e5);
  background: var(--bg-tertiary, #f6f8fa);
  border-radius: 0 4px 4px 0;
}
:deep(.markdown-content code) {
  font-family: var(--code-font-family, ui-monospace, SFMono-Regular, monospace);
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}
:deep(.markdown-content pre) {
  background: var(--bg-tertiary, #f6f8fa);
  border: 1px solid var(--border-color, #e1e4e8);
  border-radius: 6px;
  padding: 1em;
  overflow: auto;
  margin: 1em 0;
}
:deep(.markdown-content pre code) {
  background-color: transparent;
  padding: 0;
  font-size: 0.8em;
  line-height: 1.45;
}
:deep(.markdown-content table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
}
:deep(.markdown-content table th),
:deep(.markdown-content table td) {
  border: 1px solid var(--border-color, #dfe2e5);
  padding: 0.6em 1em;
}
:deep(.markdown-content table th) {
  font-weight: 600;
  background: var(--bg-tertiary, #f6f8fa);
  color: #1e293b;
}
:deep(.markdown-content a) { color: var(--text-link, #0366d6); text-decoration: none; }
:deep(.markdown-content a:hover) { text-decoration: underline; }
:deep(.markdown-content img) { max-width: 100%; height: auto; }
:deep(.markdown-content hr) { height: 0.25em; padding: 0; margin: 1.5em 0; background-color: var(--border-color, #e1e4e8); border: 0; }
:deep(.markdown-content strong) { font-weight: 600; }
:deep(.markdown-content em) { font-style: italic; }

/* ==================== 用户消息折叠 ==================== */
.user-msg-wrapper {
  position: relative;
}

.user-msg-collapsed {
  max-height: 4.5em;
  overflow: hidden;
  position: relative;
}

.user-msg-collapsed::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2em;
  background: linear-gradient(transparent, var(--card-bg, #ffffff));
  pointer-events: none;
}

.user-msg-expand-btn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-link, #3b82f6);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  transition: background 0.15s;
}

.user-msg-expand-btn:hover {
  background: rgba(59, 130, 246, 0.08);
}
</style>
