<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores'
import { ElIcon, ElTooltip } from 'element-plus'
import {
  User,
  Document,
  Search,
  List,
  PieChart,
  QuestionFilled,
  Loading,
  CircleCheck,
  CircleClose,
  Refresh,
  Setting,
  InfoFilled
} from '@element-plus/icons-vue'

// Crown图标在element-plus/icons-vue中可能不存在，使用其他图标替代
import { StarFilled } from '@element-plus/icons-vue'

const chatStore = useChatStore()

const showConfigPanel = ref(false)
const loading = ref(false)
const selectedAgent = ref<any>(null)

const statusColors = {
  idle: 'success',
  running: 'primary',
  connecting: 'warning',
  disconnected: 'danger'
} as const

const typeIcons = {
  assistant: User,
  code_assistant: Document,
  research_assistant: Search,
  task_manager: List,
  data_analyst: PieChart
} as const

const typeColors = {
  assistant: 'blue',
  code_assistant: 'green',
  research_assistant: 'orange',
  task_manager: 'purple',
  data_analyst: 'cyan'
} as const

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'idle':
      return CircleCheck
    case 'running':
      return Loading
    case 'connecting':
      return Loading
    case 'disconnected':
      return CircleClose
    default:
      return QuestionFilled
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'idle':
      return '空闲'
    case 'running':
      return '运行中'
    case 'connecting':
      return '连接中'
    case 'disconnected':
      return '断开连接'
    default:
      return '未知'
  }
}

const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleDateString('zh-CN')
}

const refreshAgents = async () => {
  if (!chatStore.sessionId) return
  
  loading.value = true
  try {
    await chatStore.fetchSessionAgents(chatStore.sessionId)
  } finally {
    loading.value = false
  }
}

const handleAgentClick = (agent: any) => {
  selectedAgent.value = agent
  showConfigPanel.value = true
}

const closeConfigPanel = () => {
  showConfigPanel.value = false
  selectedAgent.value = null
}

// 移除未使用的formatConfigValue函数

// 监听session变化，自动刷新agents
watch(() => chatStore.sessionId, (newSessionId) => {
  if (newSessionId) {
    refreshAgents()
  }
})

onMounted(() => {
  if (chatStore.sessionId) {
    refreshAgents()
  }
})
</script>

<template>
  <div 
    class="col-span-12 lg:col-span-3 flex-col gap-4 overflow-y-auto pr-1"
    :class="{
      'flex': !chatStore.isMobile || chatStore.showLeftSidebar,
      'hidden': chatStore.isMobile && !chatStore.showLeftSidebar,
      'absolute inset-x-2 top-20 bottom-4 z-40 bg-gray-50 p-3 rounded-lg shadow-xl border': chatStore.isMobile && chatStore.showLeftSidebar
    }"
  >
    <!-- 移动端标题 -->
    <div v-if="chatStore.isMobile && chatStore.showLeftSidebar" class="flex justify-between items-center lg:hidden mb-4">
      <span class="text-sm font-semibold text-gray-700">Session Agents</span>
      <el-button size="small" @click="chatStore.showLeftSidebar = false">✕</el-button>
    </div>

    <!-- Agent面板标题 -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-gray-900">Session Agents</h3>
        <el-tooltip content="点击Agent查看详情，使用 @agent名称 发送消息给指定agent" placement="top">
          <el-icon :size="14" class="text-gray-400 cursor-help">
            <InfoFilled />
          </el-icon>
        </el-tooltip>
      </div>
      <el-button 
        size="small" 
        :icon="Refresh" 
        :loading="loading" 
        @click="refreshAgents"
        class="!p-1 !h-6 !w-6"
        :disabled="!chatStore.sessionId"
      />
    </div>

    <!-- Agent列表 -->
    <div class="space-y-3">
      <div 
        v-for="agent in chatStore.agents" 
        :key="agent.agent_id"
        class="bg-white rounded-lg border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 cursor-pointer"
        :class="{
          'ring-2 ring-blue-500': chatStore.agentId === agent.agent_id,
          'ring-2 ring-yellow-500': agent.role === 'main_agent' || agent.role === 'main-agent'
        }"
        @click="handleAgentClick(agent)"
      >
        <div class="flex items-start justify-between mb-2">
          <div class="flex items-center gap-2">
            <el-icon 
              :size="16" 
              :color="typeColors[agent.type as keyof typeof typeColors] || 'gray'"
            >
              <component :is="typeIcons[agent.type as keyof typeof typeIcons] || QuestionFilled" />
            </el-icon>
            <span class="text-sm font-medium text-gray-900 truncate">{{ agent.name }}</span>
            <el-icon 
              v-if="agent.role === 'main_agent' || agent.role === 'main-agent'" 
              :size="12" 
              class="text-yellow-500"
              title="Main Agent (默认)"
            >
              <StarFilled />
            </el-icon>
          </div>
          <el-tag 
            size="small" 
            :type="agent.status ? statusColors[agent.status as keyof typeof statusColors] || 'info' : 'info'"
            class="!text-xs"
          >
            <el-icon :size="12" class="mr-1">
              <component :is="getStatusIcon(agent.status || 'disconnected')" />
            </el-icon>
            {{ getStatusText(agent.status || 'disconnected') }}
          </el-tag>
        </div>

        <p class="text-xs text-gray-600 mb-3 line-clamp-2">
          {{ agent.description || `Agent ID: ${agent.agent_id}` }}
        </p>

        <div class="flex items-center justify-between text-xs text-gray-500">
          <div class="flex items-center gap-4">
            <div class="flex items-center gap-1">
              <span class="text-gray-400">角色:</span>
              <span class="font-medium">{{ agent.role || '未指定' }}</span>
            </div>
            <div class="flex items-center gap-1">
              <span class="text-gray-400">配置:</span>
              <span class="font-medium">{{ agent.config_id?.slice(0, 8) || 'default' }}</span>
            </div>
          </div>
          <span class="text-gray-400">{{ formatDate(agent.created_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="chatStore.agents.length === 0 && !loading" class="text-center py-8">
      <el-icon :size="48" class="text-gray-300 mb-2">
        <User />
      </el-icon>
      <p class="text-sm text-gray-500">Session中暂无Agent</p>
      <p class="text-xs text-gray-400 mt-1">请先连接到session</p>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="text-center py-8">
      <el-icon :size="24" class="text-gray-400 animate-spin">
        <Loading />
      </el-icon>
      <p class="text-sm text-gray-500 mt-2">加载中...</p>
    </div>

    <!-- Agent详情面板 -->
    <div 
      v-if="showConfigPanel && selectedAgent"
      class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
      @click.self="closeConfigPanel"
    >
      <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-hidden">
        <!-- 面板头部 -->
        <div class="flex items-center justify-between p-4 border-b">
          <div class="flex items-center gap-3">
            <el-icon 
              :size="20" 
              :color="selectedAgent.type ? typeColors[selectedAgent.type as keyof typeof typeColors] || 'gray' : 'gray'"
            >
              <component :is="selectedAgent.type ? typeIcons[selectedAgent.type as keyof typeof typeIcons] || QuestionFilled : QuestionFilled" />
            </el-icon>
            <div>
              <h3 class="text-lg font-semibold text-gray-900">{{ selectedAgent.name }}</h3>
              <p class="text-sm text-gray-500">{{ selectedAgent.description || `Agent ID: ${selectedAgent.agent_id}` }}</p>
            </div>
          </div>
          <el-button 
            size="small" 
            @click="closeConfigPanel"
            class="!p-1 !h-8 !w-8"
          >
            ✕
          </el-button>
        </div>

        <!-- 面板内容 -->
        <div class="p-4 overflow-y-auto max-h-[calc(80vh-80px)]">
          <!-- Agent基本信息 -->
          <div class="mb-6">
            <h4 class="text-sm font-medium text-gray-900 mb-3">基本信息</h4>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="text-xs text-gray-500">Agent ID</label>
                <p class="text-sm font-mono bg-gray-50 p-2 rounded">{{ selectedAgent.agent_id }}</p>
              </div>
              <div>
                <label class="text-xs text-gray-500">角色</label>
                <div class="flex items-center gap-1">
                  <span class="text-sm">{{ selectedAgent.role || '未指定' }}</span>
                  <el-icon 
                    v-if="selectedAgent.role === 'main_agent' || selectedAgent.role === 'main-agent'" 
                    :size="12" 
                    class="text-yellow-500"
                  >
                    <StarFilled />
                  </el-icon>
                </div>
              </div>
              <div>
                <label class="text-xs text-gray-500">配置ID</label>
                <p class="text-sm font-mono">{{ selectedAgent.config_id }}</p>
              </div>
              <div>
                <label class="text-xs text-gray-500">创建时间</label>
                <p class="text-sm">{{ new Date(selectedAgent.created_at).toLocaleString() }}</p>
              </div>
            </div>
          </div>

          <!-- 使用说明 -->
          <div class="mb-6 p-3 bg-blue-50 rounded border border-blue-200">
            <h4 class="text-sm font-medium text-blue-900 mb-2">如何使用此Agent</h4>
            <ul class="text-xs text-blue-800 space-y-1">
              <li>• 在输入框中输入 <code class="bg-blue-100 px-1 rounded">@{{ selectedAgent.name || selectedAgent.agent_id?.slice(0, 8) || 'agent' }}</code> 发送消息给此Agent</li>
              <li>• 或直接输入 <code class="bg-blue-100 px-1 rounded">@{{ selectedAgent.agent_id?.slice(0, 8) || 'agent' }}</code> 使用ID引用</li>
              <li>• 如果不指定@mention，消息将发送给默认Agent (role为main_agent或main-agent)</li>
            </ul>
          </div>

          <!-- 无配置信息 -->
          <div class="text-center py-8 text-gray-500">
            <el-icon :size="32" class="mb-2">
              <Setting />
            </el-icon>
            <p>暂无详细配置信息</p>
            <p class="text-xs mt-1">配置信息存储在server端</p>
          </div>
        </div>

        <!-- 面板底部 -->
        <div class="p-4 border-t bg-gray-50">
          <div class="flex justify-end gap-2">
            <el-button size="small" @click="closeConfigPanel">关闭</el-button>
            <el-button 
              type="primary" 
              size="small"
              @click="() => {
                const agentName = selectedAgent.name || selectedAgent.agent_id?.slice(0, 8) || 'agent';
                chatStore.input = `@${agentName} `;
                closeConfigPanel();
              }"
            >
              发送消息给此Agent
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.overflow-y-auto::-webkit-scrollbar {
  width: 6px;
}

.overflow-y-auto::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.overflow-y-auto::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}
</style>