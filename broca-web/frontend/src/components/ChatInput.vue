<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useChatStore, useAgentStore, useSocketStore } from '@/stores'
import { uploadFile, isStorageConfigured } from '@/utils/upload'
import { commandsApi, type CommandInfo } from '@/api/commands'

const chatStore = useChatStore()
const agentStore = useAgentStore()
const socketStore = useSocketStore()

// 文件上传相关状态
const fileInputRef = ref<HTMLInputElement>()
const pendingFiles = ref<
  Array<{
    file: File
    id: string
    status: 'pending' | 'uploading' | 'success' | 'error'
    progress: number
    error?: string
    uploadedData?: {
      name: string
      url: string
      path: string
      size: number
      type: string
    }
  }>
>([])

const isUploading = ref(false)

const showMentionSuggestions = ref(false)
const mentionSuggestions = ref<Array<{ id: string; name: string }>>([])
const mentionSearch = ref('')
const selectedMentionIndex = ref(-1)
const mentionSuggestionsRef = ref<HTMLElement>()
const justSelectedMention = ref(false)

// 所有可用命令列表（从后端获取）
const allCommands = ref<CommandInfo[]>([])
const showCommandSuggestions = ref(false)
const commandSuggestions = ref<CommandInfo[]>([])
const commandSearch = ref('')
const selectedCommandIndex = ref(-1)
const commandSuggestionsRef = ref<HTMLElement>()
const justSelectedCommand = ref(false)

// 获取命令列表
const fetchCommands = async () => {
  try {
    const res = await commandsApi.getCommands()
    allCommands.value = res.commands || []
  } catch (e) {
    console.warn('获取命令列表失败:', e)
    // 后端不可用时使用静态命令列表
    allCommands.value = [
      {
        name: 'help',
        description: '显示命令帮助',
        short_description: '显示命令帮助',
        type: 'local',
        argument_hint: '[command_name]',
      },
      { name: 'init', description: '初始化项目', short_description: '初始化项目', type: 'prompt', argument_hint: '' },
      {
        name: 'plan',
        description: '生成计划文档',
        short_description: '生成计划文档',
        type: 'prompt',
        argument_hint: '<目标描述>',
      },
    ]
  }
}

// 监听输入变化，检测@mention 和 /command
watch(
  () => chatStore.input,
  (newValue) => {
    // 如果刚刚选择了mention或command，跳过检测
    if (justSelectedMention.value || justSelectedCommand.value) {
      return
    }

    // ---- 检测 /command ----
    // 只在行首或空格后检测 / 命令
    const slashIndex = newValue.lastIndexOf('/')
    if (slashIndex !== -1 && (slashIndex === 0 || newValue[slashIndex - 1] === ' ')) {
      const afterSlash = newValue.substring(slashIndex + 1)
      const spaceIndex = afterSlash.indexOf(' ')

      // 只有 / 后面还没出现空格，或者 / 后面有内容时才显示建议
      if (spaceIndex === -1) {
        // 如果 / 是输入的第一个字符且后面跟着空格，不显示建议
        if (afterSlash.length > 0) {
          const searchTerm = afterSlash
          commandSearch.value = searchTerm

          // 过滤命令
          commandSuggestions.value = allCommands.value.filter((cmd) =>
            cmd.name.toLowerCase().startsWith(searchTerm.toLowerCase())
          )

          if (commandSuggestions.value.length > 0) {
            // 如果命令列表显示，关闭mention
            showMentionSuggestions.value = false
            showCommandSuggestions.value = true
            selectedCommandIndex.value = 0
          } else {
            showCommandSuggestions.value = false
          }
        } else {
          // 只输入了 /，显示所有命令
          commandSearch.value = ''
          commandSuggestions.value = allCommands.value

          if (commandSuggestions.value.length > 0) {
            showMentionSuggestions.value = false
            showCommandSuggestions.value = true
            selectedCommandIndex.value = 0
          } else {
            showCommandSuggestions.value = false
          }
        }
        return // /command 检测优先，跳过后续 @mention 检测
      } else if (spaceIndex > 0) {
        // / 后面有内容后有空格，检查是否是精确匹配
        const searchTerm = afterSlash.substring(0, spaceIndex)
        const isExactMatch = allCommands.value.some((cmd) => cmd.name.toLowerCase() === searchTerm.toLowerCase())
        if (isExactMatch) {
          showCommandSuggestions.value = false
          // 命令已完整，继续检测 @mention
        } else {
          showCommandSuggestions.value = false
        }
      } else {
        showCommandSuggestions.value = false
      }
    } else {
      showCommandSuggestions.value = false
    }

    // ---- 检测 @mention ----
    const lastAt = newValue.lastIndexOf('@')
    if (lastAt !== -1) {
      const afterAt = newValue.substring(lastAt + 1)
      const spaceIndex = afterAt.indexOf(' ')

      if (spaceIndex === -1 || spaceIndex > 0) {
        const searchTerm = spaceIndex === -1 ? afterAt : afterAt.substring(0, spaceIndex)
        mentionSearch.value = searchTerm

        // 如果@后面有空格且搜索词已精确匹配某个agent，说明mention已完成，不再显示建议
        if (spaceIndex !== -1) {
          const isExactMatch = agentStore.agents.some(
            (agent) =>
              agent.name?.toLowerCase() === searchTerm.toLowerCase() ||
              agent.agent_id.toLowerCase() === searchTerm.toLowerCase()
          )
          if (isExactMatch) {
            showMentionSuggestions.value = false
            return
          }
        }

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

// 选择命令
const selectCommand = (commandName: string) => {
  const input = chatStore.input
  const slashIndex = input.lastIndexOf('/')
  if (slashIndex !== -1) {
    const beforeSlash = input.substring(0, slashIndex)
    const afterSlash = input.substring(slashIndex)
    const spaceIndex = afterSlash.indexOf(' ')

    let replacement = ''
    if (spaceIndex === -1) {
      replacement = `${beforeSlash}/${commandName} `
    } else {
      replacement = `${beforeSlash}/${commandName}${afterSlash.substring(spaceIndex)}`
    }

    // 设置标志，表示刚刚选择了command
    justSelectedCommand.value = true

    // 先关闭command列表
    showCommandSuggestions.value = false
    commandSearch.value = ''
    selectedCommandIndex.value = -1

    // 设置输入值
    chatStore.input = replacement

    // 100ms后重置标志
    setTimeout(() => {
      justSelectedCommand.value = false
    }, 100)
  } else {
    showCommandSuggestions.value = false
    commandSearch.value = ''
    selectedCommandIndex.value = -1
  }
}

// 处理键盘事件
const handleKeyDown = (event: KeyboardEvent) => {
  // 优先处理命令建议
  if (showCommandSuggestions.value && commandSuggestions.value.length > 0) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        selectedCommandIndex.value = Math.min(selectedCommandIndex.value + 1, commandSuggestions.value.length - 1)
        return
      case 'ArrowUp':
        event.preventDefault()
        selectedCommandIndex.value = Math.max(selectedCommandIndex.value - 1, 0)
        return
      case 'Enter':
        event.preventDefault()
        if (selectedCommandIndex.value >= 0 && selectedCommandIndex.value < commandSuggestions.value.length) {
          const suggestion = commandSuggestions.value[selectedCommandIndex.value]
          if (suggestion) {
            selectCommand(suggestion.name)
          }
        }
        return
      case 'Escape':
        showCommandSuggestions.value = false
        return
    }
  }

  // 处理mention建议
  if (showMentionSuggestions.value && mentionSuggestions.value.length > 0) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        selectedMentionIndex.value = Math.min(selectedMentionIndex.value + 1, mentionSuggestions.value.length - 1)
        return
      case 'ArrowUp':
        event.preventDefault()
        selectedMentionIndex.value = Math.max(selectedMentionIndex.value - 1, 0)
        return
      case 'Enter':
        event.preventDefault()
        if (selectedMentionIndex.value >= 0 && selectedMentionIndex.value < mentionSuggestions.value.length) {
          const suggestion = mentionSuggestions.value[selectedMentionIndex.value]
          if (suggestion) {
            selectMention(suggestion.id, suggestion.name)
          }
        }
        return
      case 'Escape':
        showMentionSuggestions.value = false
        return
    }
  }

  // 没有建议列表显示时，Enter 发送消息
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSendMessage()
  }
}

// 点击外部关闭mention/command列表
const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  const mentionList = mentionSuggestionsRef.value
  const cmdList = commandSuggestionsRef.value

  // 检查是否点击在command列表外部
  if (showCommandSuggestions.value && cmdList && !cmdList.contains(target)) {
    showCommandSuggestions.value = false
    commandSearch.value = ''
    selectedCommandIndex.value = -1
  }

  // 检查是否点击在mention列表外部
  if (showMentionSuggestions.value && mentionList && !mentionList.contains(target)) {
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

// 处理command列表点击事件，阻止事件冒泡
const handleCommandClick = (event: MouseEvent, commandName: string) => {
  event.stopPropagation()
  selectCommand(commandName)
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
  if (!chatStore.runnerAlive) return false

  // 解析@mention
  const { cleanText } = chatStore.parseMention(text)
  const hasValidText = cleanText.trim().length > 0

  // 如果有文件正在上传，不能发送
  if (isAnyUploading.value) return false

  // 有文本内容 或 有已上传成功的文件 都可以发送
  return hasValidText || allFilesUploaded.value
})

// 添加和移除全局点击事件监听器
onMounted(async () => {
  document.addEventListener('click', handleClickOutside)
  // 获取命令列表
  await fetchCommands()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

// 触发文件选择
const triggerFileSelect = () => {
  fileInputRef.value?.click()
}

// 处理文件选择
const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  if (!target.files) return

  const files = Array.from(target.files)
  if (files.length === 0) return

  // 为每个文件创建待上传记录
  files.forEach((file) => {
    const id = Math.random().toString(36).substr(2, 9)
    pendingFiles.value.push({
      file,
      id,
      status: 'pending',
      progress: 0,
    })
  })

  // 重置 input 以便下次可以选择相同文件
  target.value = ''

  // 自动开始上传
  await uploadPendingFiles()
}

// 移除待上传文件
const removePendingFile = (id: string) => {
  const index = pendingFiles.value.findIndex((f) => f.id === id)
  if (index !== -1) {
    const record = pendingFiles.value[index]
    if (!record) return
    // 如果文件正在上传，不能移除（需要取消上传功能，这里简化为不允许移除）
    if (record.status === 'uploading') {
      return
    }
    pendingFiles.value.splice(index, 1)
  }
}

// 上传单个文件
const uploadSingleFile = async (
  fileRecord: (typeof pendingFiles.value)[0]
): Promise<{
  name: string
  url: string
  path: string
  size: number
  type: string
} | null> => {
  const { file, id } = fileRecord

  // 检查存储是否已配置
  if (!isStorageConfigured()) {
    console.error('[Upload] No storage backend configured. Please set VITE_CLOUDFLARE_* or VITE_SUPABASE_* env vars.')
    const index = pendingFiles.value.findIndex((f) => f.id === id)
    if (index !== -1) {
      const record = pendingFiles.value[index]
      if (record) {
        record.status = 'error'
        record.error = '存储未配置，请联系管理员'
      }
    }
    return null
  }

  // 更新状态为上传中
  const index = pendingFiles.value.findIndex((f) => f.id === id)
  if (index === -1) return null

  const fileRecordRef = pendingFiles.value[index]
  if (!fileRecordRef) return null

  fileRecordRef.status = 'uploading'
  fileRecordRef.progress = 30

  try {
    // 使用统一的 uploadFile 上传（不再依赖 userId，路径为 uploads/日期/文件名）
    const result = await uploadFile(file)
    fileRecordRef.progress = 80

    // 更新状态为成功
    if (index !== -1) {
      const record = pendingFiles.value[index]
      if (record) {
        record.status = 'success'
        record.progress = 100
        record.uploadedData = result
      }
    }

    const successRecord = pendingFiles.value[index]
    return successRecord?.uploadedData ?? null
  } catch (error: any) {
    console.error('文件上传失败:', error)
    if (index !== -1) {
      const record = pendingFiles.value[index]
      if (record) {
        record.status = 'error'
        record.error = error.message || '上传失败'
      }
    }
    return null
  }
}

// 上传所有待上传文件
const uploadPendingFiles = async () => {
  if (isUploading.value) return

  const pending = pendingFiles.value.filter((f) => f.status === 'pending')
  if (pending.length === 0) return

  isUploading.value = true

  // 串行上传（避免并发问题）
  for (const fileRecord of pending) {
    if (fileRecord.status === 'pending') {
      await uploadSingleFile(fileRecord)
    }
  }

  isUploading.value = false
}

// 获取文件图标
const getFileIcon = (file: File) => {
  const type = file.type.toLowerCase()
  if (type.startsWith('image/')) return '🖼️'
  if (type.startsWith('video/')) return '📹'
  if (type.startsWith('audio/')) return '🎵'
  if (type.includes('pdf')) return '📄'
  if (type.includes('word') || type.includes('document')) return '📝'
  if (type.includes('excel') || type.includes('spreadsheet')) return '📊'
  if (type.includes('text/')) return '📃'
  return '📦'
}

// 格式化文件大小
const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

// 检查是否所有文件都已上传成功
const allFilesUploaded = computed(() => {
  const files = pendingFiles.value
  return files.length > 0 && files.every((f) => f.status === 'success')
})

// 检查是否正在上传
const isAnyUploading = computed(() => {
  return pendingFiles.value.some((f) => f.status === 'uploading')
})

// 处理发送消息（包含文件上传）
const handleSendMessage = async () => {
  // 如果刚选择了命令或mention，跳过发送
  if (justSelectedCommand.value || justSelectedMention.value) {
    return
  }

  const text = chatStore.input.trim()
  const { targetAgentId, cleanText } = chatStore.parseMention(text)

  if (!cleanText.trim() && pendingFiles.value.length === 0) {
    return
  }

  // 检查是否为 /redo 命令
  if (cleanText.trim() === '/redo') {
    chatStore.input = ''
    await socketStore.sendRedo({
      receiverId: targetAgentId || agentStore.currentAgentId,
    })
    return
  }

  // 如果有待上传的文件，先上传
  const pending = pendingFiles.value.filter((f) => f.status === 'pending')
  if (pending.length > 0) {
    await uploadPendingFiles()
  }

  // 检查是否有上传失败的文件
  const failedFiles = pendingFiles.value.filter((f) => f.status === 'error')
  if (failedFiles.length > 0) {
    // 可以提示用户，但继续发送成功的文件
    console.warn(
      '部分文件上传失败:',
      failedFiles.map((f) => f.error)
    )
  }

  // 获取上传成功的文件数据
  const uploadedFiles = pendingFiles.value
    .filter((f) => f.status === 'success')
    .map((f) => {
      const data = f.uploadedData
      if (!data) return null
      return {
        name: data.name,
        url: data.url,
        path: data.path,
        size: data.size,
        type: data.type,
        upload_time: new Date().toISOString(),
      }
    })
    .filter((f): f is NonNullable<typeof f> => f !== undefined)

  // 清空待上传文件列表
  pendingFiles.value = []

  // 清空输入框
  chatStore.input = ''

  // 调用 chatStore 的发送方法，传递文件数据
  // targetAgentId 可能是 null，转换为 undefined
  await chatStore.sendUserMessage(cleanText, targetAgentId || undefined, uploadedFiles)
}
</script>

<template>
  <div class="bg-white rounded-lg border shadow-sm p-1 sm:p-2 relative">
    <!-- 目标agent提示 -->
    <div class="mb-2 text-xs text-gray-500 flex items-center gap-1">
      <span>发送给:</span>
      <span class="font-medium text-blue-600">{{ targetAgentDisplay }}</span>
    </div>

    <!-- 文件预览区域 -->
    <div v-if="pendingFiles.length > 0" class="mb-2 space-y-1 max-h-32 overflow-y-auto">
      <div
        v-for="fileRecord in pendingFiles"
        :key="fileRecord.id"
        class="flex items-center gap-2 p-2 bg-gray-50 rounded border text-xs"
        :class="{
          'border-red-300 bg-red-50': fileRecord.status === 'error',
          'border-green-300 bg-green-50': fileRecord.status === 'success',
          'border-blue-300 bg-blue-50': fileRecord.status === 'uploading',
        }"
      >
        <span class="text-lg">{{ getFileIcon(fileRecord.file) }}</span>
        <div class="flex-1 min-w-0">
          <div class="font-medium truncate">
            {{ fileRecord.file.name }}
          </div>
          <div class="text-gray-500 text-xs">
            {{ formatFileSize(fileRecord.file.size) }}
            <span v-if="fileRecord.status === 'uploading'"> - 上传中... {{ fileRecord.progress }}%</span>
            <span v-if="fileRecord.status === 'success'"> - 上传成功</span>
            <span v-if="fileRecord.status === 'error'" class="text-red-600"> - {{ fileRecord.error }}</span>
          </div>
        </div>
        <!-- 删除按钮（非上传中状态可删除） -->
        <button
          v-if="fileRecord.status !== 'uploading'"
          type="button"
          class="text-gray-400 hover:text-red-500 p-1"
          @click="removePendingFile(fileRecord.id)"
        >
          ✕
        </button>
        <!-- 上传进度条 -->
        <div v-if="fileRecord.status === 'uploading'" class="w-12 h-1 bg-gray-200 rounded overflow-hidden">
          <div class="h-full bg-blue-500 transition-all" :style="{ width: fileRecord.progress + '%' }" />
        </div>
      </div>
    </div>

    <div class="flex gap-2">
      <div class="flex-1 relative">
        <!-- 隐藏的文件输入 -->
        <input ref="fileInputRef" type="file" multiple class="hidden" @change="handleFileChange" />

        <el-input
          v-model="chatStore.input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          :placeholder="chatStore.runnerAlive ? '输入/执行命令，@指定agent' : '进程未运行，无法发送消息'"
          :disabled="!chatStore.runnerAlive || isUploading"
          size="default"
          @keydown="handleKeyDown"
        />

        <!-- /command 建议列表 -->
        <div
          v-if="showCommandSuggestions && commandSuggestions.length > 0"
          ref="commandSuggestionsRef"
          class="absolute bottom-full left-0 right-0 mb-1 bg-white border rounded-lg shadow-lg z-50 max-h-48 overflow-y-auto"
          @click.stop
        >
          <div
            v-for="(suggestion, index) in commandSuggestions"
            :key="suggestion.name"
            class="px-3 py-2 hover:bg-gray-50 cursor-pointer border-b last:border-b-0"
            :class="{ 'bg-blue-50': index === selectedCommandIndex }"
            @click="handleCommandClick($event, suggestion.name)"
          >
            <div class="flex items-center gap-2">
              <span class="text-green-600 font-mono font-bold">/</span>
              <div class="flex-1 min-w-0">
                <div class="font-medium text-gray-900 font-mono">
                  {{ suggestion.name }}
                </div>
                <div class="text-xs text-gray-500 truncate">
                  {{ suggestion.short_description || suggestion.description }}
                </div>
              </div>
            </div>
          </div>
        </div>

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
              <span class="text-blue-600">@</span>
              <span class="font-medium text-gray-900">{{ suggestion.name }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 文件上传按钮 -->
      <el-button
        type="default"
        :disabled="!chatStore.runnerAlive || isUploading"
        size="default"
        class="!px-3"
        title="上传文件"
        @click="triggerFileSelect"
      >
        📎
      </el-button>

      <el-button
        type="primary"
        :disabled="!chatStore.runnerAlive || !canSendMessage || isUploading"
        size="default"
        @click="handleSendMessage"
      >
        <span class="hidden sm:inline">Send</span>
        <span class="sm:hidden">➤</span>
      </el-button>
    </div>
  </div>
</template>
