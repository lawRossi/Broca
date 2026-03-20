<script setup lang="ts">
import { useChatStore } from '@/stores'
import type { Message } from '@/api/brocaSocket'
import { formatBeijingTimeShort } from '@/utils/time'

const chatStore = useChatStore()

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
    // 显示发送给谁
    // 优先使用receiver_id（实时消息），如果没有则使用agent_id（历史消息）
    const targetAgentId = message.receiver_id || message.agent_id
    if (targetAgentId && targetAgentId !== chatStore.agentId) {
      const targetAgent = chatStore.agents.find(a => a.agent_id === targetAgentId)
      const targetName = targetAgent?.name || targetAgentId
      return `You → @${targetName}`
    }
    return 'You'
  } else if (message.message_type === 'agent_response' || message.role === 'assistant') {
    // 显示来自哪个agent
    // 优先使用sender_id（实时消息），如果没有则使用agent_id（历史消息）
    const senderAgentId = message.sender_id || message.agent_id
    if (senderAgentId && senderAgentId !== chatStore.agentId) {
      const senderAgent = chatStore.agents.find(a => a.agent_id === senderAgentId)
      const senderName = senderAgent?.name || senderAgentId
      return `@${senderName}`
    }
    return agentName
  } else if (message.message_type === 'error' || message.message_type === 'agent_error') {
    return 'Error'
  } else if (message.message_type === 'tool_call') {
    // 显示来自哪个agent的工具调用
    // 优先使用sender_id（实时消息），如果没有则使用agent_id（历史消息）
    const senderAgentId = message.sender_id || message.agent_id
    if (senderAgentId && senderAgentId !== chatStore.agentId) {
      const senderAgent = chatStore.agents.find(a => a.agent_id === senderAgentId)
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
  return !!(getReasoningContentFromData(message))
}

const getReasoningContent = (message: Message) => {
  return getReasoningContentFromData(message)
}
</script>

<template>
  <div
    class="rounded-lg p-2 sm:p-3 transition-all duration-200"
    :class="getBgClass(message)"
  >
    <div 
      v-if="message.message_type !== 'system_message' && message.role !== 'system'"
      class="flex items-center justify-between gap-2 mb-2"
    >
      <div class="flex items-center gap-2">
        <span class="text-lg">{{ getIcon(message) }}</span>
        <span class="font-semibold text-sm" :class="getHeaderColor(message)">
          {{ getSenderName(message, chatStore.agentName) }}
        </span>
      </div>
      <div class="text-xs opacity-70">
        {{ formatBeijingTimeShort(message.timestamp) }}
      </div>
    </div>

    <div>
      <div v-if="(message.message_type === 'agent_response' && hasReasoningContent(message))" class="mb-2">
        <el-button 
          size="small" 
          type="default" 
          @click="chatStore.toggleReasoning(message.message_id)"
          class="!text-amber-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
        >
          <span class="flex items-center gap-1">
            <span>{{ getShowReasoning(message.message_id) ? '▼' : '▶' }}</span>
            <span class="text-xs">推理过程</span>
          </span>
        </el-button>

        <div v-if="getShowReasoning(message.message_id)" class="mt-2 p-3 bg-amber-50 rounded-lg border border-amber-200">
          <div class="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1">
            <span>🤔</span>
            <span>推理过程</span>
          </div>
          <pre class="text-xs font-mono text-amber-800 whitespace-pre-wrap break-words leading-relaxed">{{ getReasoningContent(message) }}</pre>
        </div>
      </div>

      <pre 
        class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-2"
        :class="getContentClass(message)"
      >{{ getContent(message) }}</pre>

      <div v-if="message.message_type === 'tool_call'" class="mt-2">
        <div v-if="message.data?.arguments" class="mb-2">
          <el-button 
            size="small" 
            type="default" 
            @click="chatStore.toggleToolParameters(message.message_id)"
            class="!text-purple-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
          >
            {{ getShowParameters(message.message_id) ? '隐藏参数' : '查看参数' }}
          </el-button>

          <div v-if="getShowParameters(message.message_id)" class="mt-1 p-2 bg-purple-100 rounded border border-purple-200">
            <div class="text-xs font-semibold text-purple-700 mb-1">参数:</div>
            <pre class="text-xs font-mono text-purple-800 whitespace-pre-wrap break-words bg-white p-2 rounded border">
{{ JSON.stringify(message.data.arguments || message.data.parameters, null, 2) }}</pre>
          </div>
        </div>
        
        <!-- 结果显示 - 只要有result就显示 -->
        <div v-if="message.data?.result !== undefined" class="mb-2">
          <el-button 
            size="small" 
            type="default" 
            @click="chatStore.toggleToolResult(message.message_id)"
            class="!text-purple-600 !p-0 !h-auto !min-h-0 !border-0 !bg-transparent !shadow-none hover:!bg-transparent"
          >
            {{ getShowResult(message.message_id) ? '隐藏结果' : '查看结果' }}
          </el-button>

          <div v-if="getShowResult(message.message_id)" class="mt-1 p-2 bg-green-50 rounded border border-green-200">
            <div class="text-xs font-semibold text-green-700 mb-1">结果:</div>
            <pre class="text-xs font-mono text-green-800 whitespace-pre-wrap break-words bg-white p-2 rounded border">
{{ typeof message.data.result === 'string' ? message.data.result : JSON.stringify(message.data.result, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
