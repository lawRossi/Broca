<script setup lang="ts">
import { useChatStore, useAgentStore, useSocketStore } from '@/stores'
import type { Message } from '@/api/brocaSocket'
import { formatBeijingTimeShort } from '@/utils/time'
import { marked } from 'marked'
import { ref, computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import FilePreview from './FilePreview.vue'

const chatStore = useChatStore()
const agentStore = useAgentStore()
const socketStore = useSocketStore()

// 文件预览状态
const showFilePreview = ref(false)
const previewFilePath = ref<string>('')
const previewFileUrl = ref<string>('')

// 显示/隐藏撤销按钮
const showActions = ref(false)

// 配置 marked 选项
marked.setOptions({
  breaks: true, // 将换行符转换为 <br>
  gfm: true, // 启用 GitHub 风格 Markdown
})

// 渲染 Markdown 内容
const renderMarkdown = (content: string): string => {
  if (!content) return ''
  try {
    return marked(content, { async: false }) as string
  } catch (e) {
    console.error('Markdown rendering error:', e)
    return content
  }
}

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
  } else if (message.message_type === 'system_message' || message.role === 'system') {
    return '💬'
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
  } else if (message.message_type === 'system_message' || message.role === 'system') {
    return 'System'
  }
  return 'Unknown'
}

const getHeaderColor = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return 'text-blue-700'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return 'text-green-700'
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return 'text-red-700'
  } else if (message.message_type === 'tool_call') {
    return 'text-purple-700'
  } else if (message.message_type === 'system_message' || message.role === 'system') {
    return 'text-gray-700'
  }
  return 'text-gray-700'
}

const getBgClass = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return 'bg-blue-50 border-l-4 border-blue-500 ml-4 sm:ml-8'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return 'bg-green-50 border-l-4 border-green-500 mr-4 sm:mr-8'
  } else if (message.message_type === 'system_message' || message.role === 'system') {
    return 'bg-gray-100 border border-gray-200 text-center text-gray-600 text-xs sm:text-sm'
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return 'bg-red-50 border-l-4 border-red-500 text-red-800'
  } else if (message.message_type === 'tool_call') {
    return 'bg-purple-50 border-l-4 border-purple-500'
  }
  return ''
}

const getContentClass = (message: Message) => {
  if (message.message_type === 'user_message' || message.role === 'user') {
    return 'text-gray-800'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    return 'text-gray-800'
  } else if (message.message_type === 'system_message' || message.role === 'system') {
    return 'font-mono'
  } else if (message.message_type === 'tool_call') {
    return 'text-purple-800'
  }
  return ''
}

const getContent = (message: Message) => {
  if (message.message_type === 'tool_call') {
    const toolName = message.data?.tool_name || 'unknown_tool'
    const status = message.data?.status
    const hasResult = message.data?.result !== undefined

    if (!hasResult) {
      return `${toolName}`
    } else if (status === true || status === 'success') {
      return `${toolName}`
    } else if (status === false || status === 'error') {
      return `${toolName}`
    } else {
      return toolName
    }
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

// 检查是否为todo_management工具调用
const isTodoManagement = (message: Message) => {
  return message.message_type === 'tool_call' && message.data?.tool_name === 'todo_management'
}

// 检查是否为ask_user工具调用
const isAskUser = (message: Message) => {
  return message.message_type === 'tool_call' && message.data?.tool_name === 'ask_user'
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

// 判断结果是否应该展开（默认展开）
const shouldExpandResult = (message: Message) => {
  if (isAskUser(message)) {
    return true
  }
  return getShowResult(message.message_id)
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
  if (!chatStore.connected || !chatStore.sessionId) {
    return false
  }
  
  // 支持撤销的消息类型
  const undoableTypes = ['user_message', 'tool_call', 'agent_response']
  if (!undoableTypes.includes(props.message.message_type)) {
    return false
  }
  
  // 检查消息是否有有效内容
  if (props.message.message_type === 'user_message') {
    const content = getContent(props.message)
    if (!content || content.trim() === '') {
      return false
    }
  }
  
  // 检查消息是否有有效内容或结果
  if (props.message.message_type === 'tool_call') {
    // 工具调用必须有结果才能撤销
    if (props.message.data?.result === undefined) {
      return false
    }
    
    // 某些只读工具不应该有撤销选项
    const readOnlyTools = ['ask_user', 'todo_management', 'glob', 'grep', 'list_dir', 'tree_dir', 'web_fetch', 'web_search']
    const toolName = props.message.data?.tool_name
    if (toolName && readOnlyTools.includes(toolName)) {
      return false
    }
  }
  
  // agent_response必须有内容
  if (props.message.message_type === 'agent_response') {
    const content = getContent(props.message)
    if (!content || content.trim() === '') {
      return false
    }
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

// 获取工具显示名称
const getToolDisplayName = (message: Message) => {
  if (message.message_type !== 'tool_call') return ''
  
  const toolName = message.data?.tool_name
  if (!toolName) return '工具调用'
  
  const toolNames: Record<string, string> = {
    'edit_file': '编辑文件',
    'write_file': '写入文件',
    'execute_code': '执行代码',
    'read_file': '读取文件',
    'task_management': '任务管理',
    'cron': '定时任务',
    'assign_task': '分配任务',
    'load_skill': '加载技能',
  }
  
  return toolNames[toolName] || toolName
}

// 确认撤销
const confirmUndo = () => {
  let messageText = '确定要撤销此操作吗？'
  let levelText = ''
  
  if (props.message.message_type === 'user_message') {
    const content = getContent(props.message)
    const preview = content.length > 50 ? content.substring(0, 50) + '...' : content
    messageText = `确定要撤销此消息吗？（将撤销整个对话轮次）\n"${preview}"`
    levelText = '（turn级别撤销）'
  } else if (props.message.message_type === 'tool_call') {
    const toolName = getToolDisplayName(props.message)
    messageText = `确定要撤销 "${toolName}" 操作吗？`
    levelText = '（step级别撤销）'
  } else if (props.message.message_type === 'agent_response') {
    const content = getContent(props.message)
    const preview = content.length > 50 ? content.substring(0, 50) + '...' : content
    messageText = `确定要撤销此回复吗？\n"${preview}"`
    levelText = '（step级别撤销）'
  }
  
  ElMessageBox.confirm(`${messageText}${levelText}`, '确认撤销', {
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
  
  try {
    await socketStore.sendUndo({
      targetMessageId: props.message.message_id,
      level: getUndoLevel.value,
      subscription: chatStore.sessionId,
      receiverId: props.message.agent_id || agentStore.currentAgentId
    })
  } catch (error) {
    console.error('撤销失败:', error)
  }
}
</script>

<template>
  <div 
    class="rounded-lg p-2 sm:p-3 transition-all duration-200 message-container"
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
        <span class="font-semibold text-sm" :class="getHeaderColor(message)">
          {{ getSenderName(message, agentStore.currentAgentName) }}
        </span>
      </div>
      
      <div class="flex items-center gap-2">
        <div class="text-xs text-gray-500 opacity-70">
          {{ formatBeijingTimeShort(message.timestamp) }}
        </div>
        
        <!-- 悬停撤销按钮 -->
        <div class="hover-actions" v-if="showActions && canUndoThisMessage">
          <el-button 
            size="small" 
            type="text" 
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
          class="!text-amber-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
          @click="chatStore.toggleReasoning(message.message_id)"
        >
          <span class="flex items-center gap-1">
            <span>{{ getShowReasoning(message.message_id) ? '▼' : '▶' }}</span>
            <span class="text-xs">思考</span>
          </span>
        </el-button>

        <div
          v-if="getShowReasoning(message.message_id)"
          class="mt-2 p-3 bg-amber-50 rounded-lg border border-amber-200"
        >
          <pre class="text-xs font-mono text-amber-800 whitespace-pre-wrap break-words leading-relaxed">{{
            getReasoningContent(message)
          }}</pre>
        </div>
      </div>

      <!-- 用户消息：内容 + 文件附件 -->
      <template v-if="message.message_type === 'user_message' || message.role === 'user'">
        <!-- 用户消息使用普通文本渲染，不使用 markdown -->
        <pre
          class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-2"
          :class="getContentClass(message)"
          >{{ getContent(message) }}</pre
        >

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
        class="markdown-content text-xs sm:text-sm leading-relaxed mb-2"
        :class="getContentClass(message)"
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
        <!-- 参数展示 -->
        <div v-if="message.data?.arguments || message.data?.parameters" class="mb-2">
          <!-- 只有非todo_management且非ask_user工具才显示切换按钮 -->
          <el-button
            v-if="!isTodoManagement(message) && !isAskUser(message)"
            size="small"
            type="default"
            class="!text-purple-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
            @click="chatStore.toggleToolParameters(message.message_id)"
          >
            {{ getShowParameters(message.message_id) ? '隐藏参数' : '查看参数' }}
          </el-button>

          <!-- 参数内容：特殊处理todo_management和ask_user -->
          <div v-if="shouldExpandParameters(message)" class="mt-1 p-2 bg-purple-100 rounded border border-purple-200">
            <div v-if="isAskUser(message)" class="text-xs font-semibold text-purple-700 mb-1">问题:</div>

            <!-- 特殊处理todo_management的todos列表 -->
            <div v-if="isTodoManagement(message) && getTodos(message)" class="bg-white p-2 rounded border">
              <div v-for="(todo, index) in getTodos(message)" :key="index" class="mb-2 last:mb-0">
                <div class="flex items-start gap-2">
                  <span class="mt-1 text-sm">
                    <span v-if="todo.status === 'completed'">✅</span>
                    <span v-else-if="todo.status === 'in_progress'">⏳</span>
                    <span v-else>⬜️</span>
                  </span>
                  <div class="flex-1">
                    <div class="text-sm font-medium text-gray-800">
                      {{ todo.name }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 特殊处理ask_user的参数 -->
            <div v-else-if="isAskUser(message) && getAskUserParams(message)" class="bg-white p-3 rounded border">
              <div class="text-sm font-medium text-gray-800 mb-2">
                {{ getAskUserParams(message).question }}
              </div>
              <div v-if="getAskUserParams(message).options?.length" class="space-y-1 ml-2">
                <div
                  v-for="(opt, optIndex) in getAskUserParams(message).options"
                  :key="optIndex"
                  class="text-xs text-gray-600 flex items-start gap-1"
                >
                  <span class="text-purple-600">•</span>
                  <span>{{ opt.name }}</span>
                  <span v-if="opt.description" class="text-gray-400">- {{ opt.description }}</span>
                </div>
              </div>
            </div>

            <!-- 其他工具显示原始JSON -->
            <pre
              v-else
              class="text-xs font-mono text-purple-800 whitespace-pre-wrap break-words bg-white p-2 rounded border"
              >{{ JSON.stringify(message.data.arguments || message.data.parameters, null, 2) }}</pre
            >
          </div>
        </div>

        <!-- 结果展示：todo_management不显示，ask_user默认展开 -->
        <div v-if="message.data?.result !== undefined && !isTodoManagement(message)" class="mb-2">
          <el-button
            v-if="!isAskUser(message)"
            size="small"
            type="default"
            class="!text-purple-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
            @click="chatStore.toggleToolResult(message.message_id)"
          >
            {{ getShowResult(message.message_id) ? '隐藏结果' : '查看结果' }}
          </el-button>

          <!-- ask_user结果默认展开 -->
          <div v-if="shouldExpandResult(message)" class="mt-1 p-2 bg-green-50 rounded border border-green-200">
            <div v-if="isAskUser(message)" class="text-xs font-semibold text-green-700 mb-1">回答:</div>

            <!-- 特殊处理ask_user结果 -->
            <div v-if="isAskUser(message) && getAskUserResult(message)" class="bg-white p-2 rounded border">
              <div class="text-sm text-gray-800">
                {{ getAskUserResult(message) }}
              </div>
            </div>

            <!-- 其他工具显示原始JSON -->
            <pre
              v-else
              class="text-xs font-mono text-green-800 whitespace-pre-wrap break-words bg-white p-2 rounded border"
              >{{
                typeof message.data.result === 'string'
                  ? message.data.result
                  : JSON.stringify(message.data.result, null, 2)
              }}</pre
            >
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
/* 消息容器样式 */
.message-container {
  position: relative;
  transition: all 0.2s ease;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
}

.message-container:hover {
  background-color: rgba(0, 0, 0, 0.02);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

/* 悬停操作按钮 */
.hover-actions {
  opacity: 0;
  transition: opacity 0.2s ease;
  margin-left: 8px;
}

.message-container:hover .hover-actions {
  opacity: 1;
}

/* 撤销按钮样式 */
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

.hover-actions .el-button.undo-button:disabled {
  color: #c0c4cc;
  background: rgba(192, 196, 204, 0.1);
  border-color: rgba(192, 196, 204, 0.2);
  cursor: not-allowed;
}

/* 不同类型的消息撤销按钮颜色不同 */
.message-container.bg-blue-50 .hover-actions .el-button.undo-button {
  color: #409eff;
  background: rgba(64, 158, 255, 0.1);
  border-color: rgba(64, 158, 255, 0.2);
}

.message-container.bg-blue-50 .hover-actions .el-button.undo-button:hover {
  background: rgba(64, 158, 255, 0.2);
  color: #409eff;
  border-color: rgba(64, 158, 255, 0.3);
}

.message-container.bg-green-50 .hover-actions .el-button.undo-button {
  color: #67c23a;
  background: rgba(103, 194, 58, 0.1);
  border-color: rgba(103, 194, 58, 0.2);
}

.message-container.bg-green-50 .hover-actions .el-button.undo-button:hover {
  background: rgba(103, 194, 58, 0.2);
  color: #67c23a;
  border-color: rgba(103, 194, 58, 0.3);
}

.message-container.bg-purple-50 .hover-actions .el-button.undo-button {
  color: #8a2be2;
  background: rgba(138, 43, 226, 0.1);
  border-color: rgba(138, 43, 226, 0.2);
}

.message-container.bg-purple-50 .hover-actions .el-button.undo-button:hover {
  background: rgba(138, 43, 226, 0.2);
  color: #8a2be2;
  border-color: rgba(138, 43, 226, 0.3);
}

/* Markdown 内容样式 */
:deep(.markdown-content) {
  word-wrap: break-word;
  overflow-wrap: break-word;
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
}

:deep(.markdown-content h1) {
  font-size: 1.5em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

:deep(.markdown-content h2) {
  font-size: 1.3em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

:deep(.markdown-content h3) {
  font-size: 1.1em;
}

:deep(.markdown-content p) {
  margin-bottom: 1em;
  line-height: 1.6;
}

:deep(.markdown-content ul),
:deep(.markdown-content ol) {
  padding-left: 2em;
  margin-bottom: 1em;
}

:deep(.markdown-content li) {
  margin-bottom: 0.25em;
}

:deep(.markdown-content blockquote) {
  margin: 1em 0;
  padding: 0 1em;
  color: #6a737d;
  border-left: 0.25em solid #dfe2e5;
  background-color: #f6f8fa;
  padding: 0.5em 1em;
  border-radius: 0 4px 4px 0;
}

:deep(.markdown-content code) {
  font-family:
    ui-monospace,
    SFMono-Regular,
    SF Mono,
    Menlo,
    Consolas,
    Liberation Mono,
    monospace;
  font-size: 0.875em;
  background-color: rgba(175, 184, 193, 0.2);
  padding: 0.2em 0.4em;
  border-radius: 3px;
}

:deep(.markdown-content pre) {
  background-color: #f6f8fa;
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
  border: 1px solid #dfe2e5;
  padding: 0.6em 1em;
}

:deep(.markdown-content table th) {
  font-weight: 600;
  background-color: #f6f8fa;
}

:deep(.markdown-content tr:nth-child(2n)) {
  background-color: #f6f8fa;
}

:deep(.markdown-content a) {
  color: #0366d6;
  text-decoration: none;
}

:deep(.markdown-content a:hover) {
  text-decoration: underline;
}

:deep(.markdown-content img) {
  max-width: 100%;
  height: auto;
}

:deep(.markdown-content hr) {
  height: 0.25em;
  padding: 0;
  margin: 1.5em 0;
  background-color: #e1e4e8;
  border: 0;
}

:deep(.markdown-content strong) {
  font-weight: 600;
}

:deep(.markdown-content em) {
  font-style: italic;
}

:deep(.markdown-content del) {
  text-decoration: line-through;
}
</style>
