<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useChatStore, useAgentStore } from '@/stores'
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

const chatStore = useChatStore()
const agentStore = useAgentStore()

const showConfigPanel = ref(false)
const loading = ref(false)

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
  loading.value = true
  try {
    await agentStore.fetchAgents()
  } finally {
    loading.value = false
  }
}

const handleAgentClick = (agentId: string) => {
  agentStore.selectAgent(agentId)
  showConfigPanel.value = true
}

const closeConfigPanel = () => {
  showConfigPanel.value = false
}

// const getConfigValue = (config: any, path: string): any => {
//   return path.split('.').reduce((obj, key) => obj?.[key], config)
// }

const formatConfigValue = (value: any): string => {
  if (Array.isArray(value)) {
    return value.join(', ')
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}

onMounted(async () => {
  await agentStore.init()
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
      <span class="text-sm font-semibold text-gray-700">Agent 面板</span>
      <el-button size="small" @click="chatStore.showLeftSidebar = false">✕</el-button>
    </div>

    <!-- Agent面板标题 -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-gray-900">Agent 面板</h3>
        <el-tooltip content="点击Agent查看配置详情" placement="top">
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
      />
    </div>

    <!-- Agent列表 -->
    <div class="space-y-3">
      <div 
        v-for="agent in agentStore.agents" 
        :key="agent.id"
        class="bg-white rounded-lg border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 cursor-pointer"
        :class="{
          'ring-2 ring-blue-500': agentStore.selectedAgentId === agent.id
        }"
        @click="handleAgentClick(agent.id)"
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
          </div>
          <el-tag 
            size="small" 
            :type="statusColors[agent.status] || 'info'"
            class="!text-xs"
          >
            <el-icon :size="12" class="mr-1">
              <component :is="getStatusIcon(agent.status)" />
            </el-icon>
            {{ getStatusText(agent.status) }}
          </el-tag>
        </div>

        <p class="text-xs text-gray-600 mb-3 line-clamp-2">{{ agent.description }}</p>

        <div class="flex items-center justify-between text-xs text-gray-500">
          <div class="flex items-center gap-4">
            <div class="flex items-center gap-1">
              <span class="text-gray-400">消息:</span>
              <span class="font-medium">{{ agent.metrics?.total_messages || 0 }}</span>
            </div>
            <div class="flex items-center gap-1">
              <span class="text-gray-400">成功率:</span>
              <span class="font-medium">{{ agent.metrics?.success_rate || 0 }}%</span>
            </div>
          </div>
          <span class="text-gray-400">{{ formatDate(agent.created_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="agentStore.agents.length === 0 && !agentStore.loading" class="text-center py-8">
      <el-icon :size="48" class="text-gray-300 mb-2">
        <User />
      </el-icon>
      <p class="text-sm text-gray-500">暂无Agent</p>
    </div>

    <!-- 加载状态 -->
    <div v-if="agentStore.loading" class="text-center py-8">
      <el-icon :size="24" class="text-gray-400 animate-spin">
        <Loading />
      </el-icon>
      <p class="text-sm text-gray-500 mt-2">加载中...</p>
    </div>

    <!-- Agent配置详情面板 -->
    <div 
      v-if="showConfigPanel && agentStore.selectedAgent"
      class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
      @click.self="closeConfigPanel"
    >
      <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-hidden">
        <!-- 面板头部 -->
        <div class="flex items-center justify-between p-4 border-b">
          <div class="flex items-center gap-3">
            <el-icon 
              :size="20" 
              :color="typeColors[agentStore.selectedAgent.type as keyof typeof typeColors] || 'gray'"
            >
              <component :is="typeIcons[agentStore.selectedAgent.type as keyof typeof typeIcons] || QuestionFilled" />
            </el-icon>
            <div>
              <h3 class="text-lg font-semibold text-gray-900">{{ agentStore.selectedAgent.name }}</h3>
              <p class="text-sm text-gray-500">{{ agentStore.selectedAgent.description }}</p>
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
                <label class="text-xs text-gray-500">ID</label>
                <p class="text-sm font-mono bg-gray-50 p-2 rounded">{{ agentStore.selectedAgent.id }}</p>
              </div>
              <div>
                <label class="text-xs text-gray-500">类型</label>
                <p class="text-sm">{{ agentStore.selectedAgent.type }}</p>
              </div>
              <div>
                <label class="text-xs text-gray-500">状态</label>
                <el-tag 
                  size="small" 
                  :type="statusColors[agentStore.selectedAgent.status] || 'info'"
                >
                  {{ getStatusText(agentStore.selectedAgent.status) }}
                </el-tag>
              </div>
              <div>
                <label class="text-xs text-gray-500">创建时间</label>
                <p class="text-sm">{{ new Date(agentStore.selectedAgent.created_at).toLocaleString() }}</p>
              </div>
            </div>
          </div>

          <!-- Agent配置 -->
          <div v-if="agentStore.selectedAgentConfig" class="mb-6">
            <h4 class="text-sm font-medium text-gray-900 mb-3">配置详情</h4>
            <div class="space-y-3">
              <div v-for="(value, key) in agentStore.selectedAgentConfig.config" :key="key">
                <label class="text-xs text-gray-500 block mb-1">{{ key }}</label>
                <div class="bg-gray-50 p-3 rounded text-sm font-mono overflow-x-auto">
                  {{ formatConfigValue(value) }}
                </div>
              </div>
            </div>
          </div>

          <!-- 性能指标 -->
          <div v-if="agentStore.selectedAgent.metrics" class="mb-6">
            <h4 class="text-sm font-medium text-gray-900 mb-3">性能指标</h4>
            <div class="grid grid-cols-3 gap-4">
              <div class="text-center p-3 bg-blue-50 rounded">
                <p class="text-2xl font-bold text-blue-600">{{ agentStore.selectedAgent.metrics.total_messages }}</p>
                <p class="text-xs text-blue-500">总消息数</p>
              </div>
              <div class="text-center p-3 bg-green-50 rounded">
                <p class="text-2xl font-bold text-green-600">{{ agentStore.selectedAgent.metrics.avg_response_time }}s</p>
                <p class="text-xs text-green-500">平均响应时间</p>
              </div>
              <div class="text-center p-3 bg-purple-50 rounded">
                <p class="text-2xl font-bold text-purple-600">{{ agentStore.selectedAgent.metrics.success_rate }}%</p>
                <p class="text-xs text-purple-500">成功率</p>
              </div>
            </div>
          </div>

          <!-- 无配置信息 -->
          <div v-else class="text-center py-8 text-gray-500">
            <el-icon :size="32" class="mb-2">
              <Setting />
            </el-icon>
            <p>暂无配置信息</p>
          </div>
        </div>

        <!-- 面板底部 -->
        <div class="p-4 border-t bg-gray-50">
          <div class="flex justify-end gap-2">
            <el-button size="small" @click="closeConfigPanel">关闭</el-button>
            <el-button type="primary" size="small">编辑配置</el-button>
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