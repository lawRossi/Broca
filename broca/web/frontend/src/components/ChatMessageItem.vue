<script setup lang="ts">
import { useChatStore, DisplayType } from '@/stores'
import type { UiMessage } from '@/stores/chat'
import { formatBeijingTimeShort } from '@/utils/time'

const chatStore = useChatStore()

defineProps<{
  message: UiMessage
}>()

const getIcon = (displayType: DisplayType) => {
  switch (displayType) {
    case DisplayType.USER: return '👤'
    case DisplayType.ASSISTANT: return '🤖'
    case DisplayType.ERROR: return '⚠️'
    case DisplayType.THINKING: return '💭'
    case DisplayType.TOOL_CALL: return '🔧'
    default: return '💬'
  }
}

const getSenderName = (displayType: DisplayType, agentName: string, message: UiMessage) => {
  switch (displayType) {
    case DisplayType.USER: 
      // 显示发送给谁
      if (message.receiver && message.receiver !== chatStore.agentId) {
        const targetAgent = chatStore.agents.find(a => a.agent_id === message.receiver)
        const targetName = targetAgent?.name || message.receiver
        return `You → @${targetName}`
      }
      return 'You'
    case DisplayType.ASSISTANT: 
      // 显示来自哪个agent
      if (message.sender && message.sender !== chatStore.agentId) {
        const senderAgent = chatStore.agents.find(a => a.agent_id === message.sender)
        const senderName = senderAgent?.name || message.sender
        return `@${senderName}`
      }
      return agentName
    case DisplayType.ERROR: return 'Error'
    case DisplayType.THINKING: return 'Thinking'
    case DisplayType.TOOL_CALL: 
      // 显示来自哪个agent的工具调用
      if (message.sender && message.sender !== chatStore.agentId) {
        const senderAgent = chatStore.agents.find(a => a.agent_id === message.sender)
        const senderName = senderAgent?.name || message.sender
        return `@${senderName} - Tool`
      }
      return 'Tool Call'
    default: return 'System'
  }
}

const getHeaderColor = (displayType: DisplayType) => {
  switch (displayType) {
    case DisplayType.USER: return 'text-blue-700'
    case DisplayType.ASSISTANT: return 'text-green-700'
    case DisplayType.ERROR: return 'text-red-700'
    case DisplayType.THINKING: return 'text-yellow-700'
    case DisplayType.TOOL_CALL: return 'text-purple-700'
    default: return 'text-gray-700'
  }
}

const getBgClass = (displayType: DisplayType) => {
  switch (displayType) {
    case DisplayType.USER: return 'bg-blue-50 border-l-4 border-blue-500 ml-4 sm:ml-8'
    case DisplayType.ASSISTANT: return 'bg-green-50 border-l-4 border-green-500 mr-4 sm:mr-8'
    case DisplayType.SYSTEM: return 'bg-gray-100 border border-gray-200 text-center text-gray-600 text-xs sm:text-sm'
    case DisplayType.ERROR: return 'bg-red-50 border-l-4 border-red-500 text-red-800'
    case DisplayType.THINKING: return 'bg-yellow-50 border-l-4 border-yellow-500 italic'
    case DisplayType.TOOL_CALL: return 'bg-purple-50 border-l-4 border-purple-500'
    default: return ''
  }
}

const getContentClass = (displayType: DisplayType) => {
  switch (displayType) {
    case DisplayType.USER:
    case DisplayType.ASSISTANT:
      return 'text-gray-800'
    case DisplayType.SYSTEM:
      return 'font-mono'
    case DisplayType.TOOL_CALL:
      return 'text-purple-800'
    default:
      return ''
  }
}
</script>

<template>
  <div
    class="rounded-lg p-2 sm:p-3 transition-all duration-200"
    :class="getBgClass(message.displayType)"
  >
    <div 
      v-if="message.displayType !== DisplayType.SYSTEM"
      class="flex items-center justify-between gap-2 mb-2"
    >
      <div class="flex items-center gap-2">
        <span class="text-lg">{{ getIcon(message.displayType) }}</span>
        <span class="font-semibold text-sm" :class="getHeaderColor(message.displayType)">
          {{ getSenderName(message.displayType, chatStore.agentName, message) }}
        </span>
      </div>
      <div class="text-xs opacity-70">
        {{ formatBeijingTimeShort(message.ts) }}
      </div>
    </div>
    
    <div>
      <pre 
        class="whitespace-pre-wrap break-words text-xs sm:text-sm leading-relaxed mb-2"
        :class="getContentClass(message.displayType)"
      >{{ message.content }}</pre>
      
      <div v-if="message.displayType === DisplayType.TOOL_CALL && message.raw.data?.arguments" class="mt-2">
        <el-button 
          size="small" 
          type="text" 
          @click="chatStore.toggleToolParameters(message.id)"
          class="!text-purple-600 !p-0 !h-auto !min-h-0"
        >
          {{ message.showParameters ? '隐藏参数' : '查看参数' }}
        </el-button>

        <div v-if="message.showParameters" class="mt-2 p-2 bg-purple-100 rounded border border-purple-200">
          <div class="text-xs font-semibold text-purple-700 mb-1">参数:</div>
          <pre class="text-xs font-mono text-purple-800 whitespace-pre-wrap break-words bg-white p-2 rounded border">
{{ JSON.stringify(message.raw.data.arguments, null, 2) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
