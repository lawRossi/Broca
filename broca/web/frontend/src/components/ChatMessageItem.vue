<script setup lang="ts">
import { useChatStore, useAgentStore } from '@/stores'
import type { Message } from '@/api/brocaSocket'
import { formatBeijingTimeShort } from '@/utils/time'

const chatStore = useChatStore()
const agentStore = useAgentStore()

defineProps<{
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
      // 如果解析成功且包含 content 字段，则返回该字段
      if (parsed && typeof parsed === 'object' && parsed.content !== undefined) {
        return parsed.content
      }
      // 否则返回原始解析结果（转换为字符串）
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
</script>

<template>
  <div class="rounded-lg p-2 sm:p-3 transition-all duration-200" :class="getBgClass(message)">
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
      <div class="text-xs text-gray-500 opacity-70">
        {{ formatBeijingTimeShort(message.timestamp) }}
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

      <pre
        class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-2"
        :class="getContentClass(message)"
      >{{ getContent(message) }}</pre>

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
            <div v-if="isAskUser(message)" class="text-xs font-semibold text-purple-700 mb-1">
              问题:
            </div>

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
            >{{ JSON.stringify(message.data.arguments || message.data.parameters, null, 2) }}</pre>
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
            <div v-if="isAskUser(message)" class="text-xs font-semibold text-green-700 mb-1">
              回答:
            </div>

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
            }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
