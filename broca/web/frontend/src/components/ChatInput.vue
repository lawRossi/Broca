<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useChatStore, useAgentStore } from '@/stores'

const chatStore = useChatStore()
const agentStore = useAgentStore()

const showMentionSuggestions = ref(false)
const mentionSuggestions = ref<Array<{ id: string; name: string }>>([])
const mentionSearch = ref('')
const selectedMentionIndex = ref(-1)
const mentionSuggestionsRef = ref<HTMLElement>()
const justSelectedMention = ref(false)

// 监听输入变化，检测@mention
watch(
  () => chatStore.input,
  (newValue) => {
    // 如果刚刚选择了mention，跳过检测
    if (justSelectedMention.value) {
      return
    }

    const lastAt = newValue.lastIndexOf('@')
    if (lastAt !== -1) {
      const afterAt = newValue.substring(lastAt + 1)
      const spaceIndex = afterAt.indexOf(' ')

      if (spaceIndex === -1 || spaceIndex > 0) {
        const searchTerm = spaceIndex === -1 ? afterAt : afterAt.substring(0, spaceIndex)
        mentionSearch.value = searchTerm

        // 过滤agents
        mentionSuggestions.value = agentStore.agents
          .filter(
            (agent) =>
              agent.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
              agent.agent_id.toLowerCase().includes(searchTerm.toLowerCase())
          )
          .map((agent) => ({
            id: agent.agent_id,
            name: agent.name || agent.agent_id,
          }))

        if (mentionSuggestions.value.length > 0) {
          showMentionSuggestions.value = true
          selectedMentionIndex.value = 0
        } else {
          showMentionSuggestions.value = false
        }
      } else {
        showMentionSuggestions.value = false
      }
    } else {
      showMentionSuggestions.value = false
    }
  }
)

// 选择mention
const selectMention = (_agentId: string, agentName: string) => {
  const input = chatStore.input
  const lastAt = input.lastIndexOf('@')
  if (lastAt !== -1) {
    const beforeAt = input.substring(0, lastAt)
    const afterAt = input.substring(lastAt)
    const spaceIndex = afterAt.indexOf(' ')

    let replacement = ''
    if (spaceIndex === -1) {
      replacement = `${beforeAt}@${agentName} `
    } else {
      replacement = `${beforeAt}@${agentName}${afterAt.substring(spaceIndex)}`
    }

    // 设置标志，表示刚刚选择了mention
    justSelectedMention.value = true

    // 先关闭mention列表
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1

    // 设置输入值
    chatStore.input = replacement

    // 100ms后重置标志
    setTimeout(() => {
      justSelectedMention.value = false
    }, 100)
  } else {
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1
  }
}

// 处理键盘事件
const handleKeyDown = (event: KeyboardEvent) => {
  if (!showMentionSuggestions.value) return

  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      selectedMentionIndex.value = Math.min(selectedMentionIndex.value + 1, mentionSuggestions.value.length - 1)
      break
    case 'ArrowUp':
      event.preventDefault()
      selectedMentionIndex.value = Math.max(selectedMentionIndex.value - 1, 0)
      break
    case 'Enter':
      if (selectedMentionIndex.value >= 0 && selectedMentionIndex.value < mentionSuggestions.value.length) {
        event.preventDefault()
        const suggestion = mentionSuggestions.value[selectedMentionIndex.value]
        if (suggestion) {
          selectMention(suggestion.id, suggestion.name)
        }
      }
      break
    case 'Escape':
      showMentionSuggestions.value = false
      break
  }
}

// 点击外部关闭mention列表
const handleClickOutside = (event: MouseEvent) => {
  if (!showMentionSuggestions.value) return

  const target = event.target as HTMLElement
  const mentionList = mentionSuggestionsRef.value

  // 如果点击的不是mention列表本身，则关闭列表
  if (mentionList && !mentionList.contains(target)) {
    showMentionSuggestions.value = false
    mentionSearch.value = ''
    selectedMentionIndex.value = -1
  }
}

// 处理mention列表点击事件，阻止事件冒泡
const handleMentionClick = (event: MouseEvent, agentId: string, agentName: string) => {
  event.stopPropagation()
  selectMention(agentId, agentName)
}

// 当前目标agent显示
const targetAgentDisplay = computed(() => {
  const { targetAgentId } = chatStore.parseMention(chatStore.input)
  if (targetAgentId) {
    const agent = agentStore.agents.find((a) => a.agent_id === targetAgentId)
    return agent?.name || targetAgentId
  }
  return agentStore.currentAgentName
})

// 检查是否可以发送消息
const canSendMessage = computed(() => {
  const text = chatStore.input.trim()
  if (!text) return false

  // 解析@mention
  const { cleanText } = chatStore.parseMention(text)

  // 检查cleanText是否为空或只包含空格
  return cleanText.trim().length > 0
})

// 添加和移除全局点击事件监听器
onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="bg-white rounded-lg border shadow-sm p-1 sm:p-2 relative">
    <!-- 目标agent提示 -->
    <div class="mb-2 text-xs text-gray-500 flex items-center gap-1">
      <span>发送给:</span>
      <span class="font-medium text-blue-600">{{ targetAgentDisplay }}</span>
    </div>

    <div class="flex gap-2">
      <div class="flex-1 relative">
        <el-input
          v-model="chatStore.input"
          placeholder="Type message... 使用 @ 指定agent"
          :disabled="!chatStore.connected"
          size="default"
          clearable
          @keyup.enter="chatStore.sendUserMessage"
          @keydown="handleKeyDown"
        />

        <!-- @mention 建议列表 -->
        <div
          v-if="showMentionSuggestions && mentionSuggestions.length > 0"
          ref="mentionSuggestionsRef"
          class="absolute bottom-full left-0 right-0 mb-1 bg-white border rounded-lg shadow-lg z-50 max-h-48 overflow-y-auto"
          @click.stop
        >
          <div
            v-for="(suggestion, index) in mentionSuggestions"
            :key="suggestion.id"
            class="px-3 py-2 hover:bg-gray-50 cursor-pointer border-b last:border-b-0"
            :class="{ 'bg-blue-50': index === selectedMentionIndex }"
            @click="handleMentionClick($event, suggestion.id, suggestion.name)"
          >
            <div class="flex items-center gap-2">
              <span class="text-blue-500">@</span>
              <span class="font-medium">{{ suggestion.name }}</span>
            </div>
          </div>
        </div>
      </div>


      <el-button
        type="primary"
        :disabled="!chatStore.connected || !canSendMessage"
        size="default"
        @click="chatStore.sendUserMessage"
      >
        <span class="hidden sm:inline">Send</span>
        <span class="sm:hidden">➤</span>
      </el-button>
    </div>
  </div>
</template>
