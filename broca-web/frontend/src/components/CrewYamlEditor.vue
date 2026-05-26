<script setup lang="ts">
/**
 * Crew YAML 编辑器组件
 * 支持语法高亮、实时校验、模板选择
 */
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useCrewStore } from '@/stores/crew'
import { useSessionStore } from '@/stores/session'
import { Document, Edit, Check, Warning } from '@element-plus/icons-vue'

const emit = defineEmits<{
  close: []
  submit: [yaml: string, sessionId: string]
}>()

const crewStore = useCrewStore()
const sessionStore = useSessionStore()

// 预置模板
const templates = {
  debate: `# 圆桌辩论模板
name: "圆桌辩论"
description: "多 Agent 圆桌讨论"

orchestrator:
  type: round-table
  max_rounds: 5

agents:
  - role: moderator
    name: "主持人"
    config: moderator_agent.md
  - role: participant
    name: "支持方"
    config: debater_agent.md
    extras:
      stance: pro
  - role: participant
    name: "反对方"
    config: debater_agent.md
    extras:
      stance: con

blackboard:
  initial_entries:
    - key: topic
      value: "请替换为讨论主题"`,
  'deep-research': `# 深度研究模板
name: "深度研究"
description: "AI Agent 深度研究"

orchestrator:
  type: supervisor-worker
  max_rounds: 3

agents:
  - role: supervisor
    name: "研究主管"
    config: coordinator_agent.md
  - role: worker
    name: "文献研究员"
    config: researcher_agent.md
  - role: worker
    name: "数据分析师"
    config: analyst_agent.md
  - role: worker
    name: "报告撰写人"
    config: writer_agent.md
  - role: worker
    name: "质量审查员"
    config: reviewer_agent.md

blackboard:
  initial_entries:
    - key: objective
      value: "请替换为研究目标"`,
  'code-review': `# 代码审查模板
name: "代码审查"
description: "多维度代码审查与质量评估"

orchestrator:
  type: consensus
  strategy: weighted
  threshold: 0.7
  weights:
    高级架构师: 1.5
    安全工程师: 1.2
    初级开发: 0.8

agents:
  - role: reviewer
    name: "高级架构师"
    config: senior_dev_agent.md
  - role: reviewer
    name: "安全工程师"
    config: security_agent.md
  - role: reviewer
    name: "初级开发"
    config: junior_dev_agent.md

blackboard:
  initial_entries:
    - key: review_target
      value: "请替换为待审查的代码"`,
}

// 状态
const localYaml = ref('')
const selectedTemplate = ref<string>('')
const selectedSessionId = ref('')
const sessionList = ref<Array<{ session_id: string; description?: string }>>([])
const isValidating = ref(false)
const isValid = ref(false)
const yamlError = ref('')

// 编辑器行数
const lineCount = computed(() => localYaml.value.split('\n').length)

// 选择模板
const selectTemplate = (templateId: string) => {
  selectedTemplate.value = templateId
  if (templateId && templates[templateId as keyof typeof templates]) {
    localYaml.value = templates[templateId as keyof typeof templates]
    isValid.value = false
    yamlError.value = ''
  }
}

// 校验 YAML
const handleValidate = async () => {
  if (!localYaml.value.trim()) {
    ElMessage.warning('请输入 YAML 配置')
    return
  }
  isValidating.value = true
  try {
    isValid.value = await crewStore.validateYaml(localYaml.value)
    if (!isValid.value) {
      yamlError.value = crewStore.validationErrors.join('\n')
    } else {
      yamlError.value = ''
    }
  } catch {
    isValid.value = false
    yamlError.value = '校验请求失败'
  } finally {
    isValidating.value = false
  }
}

// 提交
const handleSubmit = async () => {
  if (!localYaml.value.trim()) {
    ElMessage.warning('请输入 YAML 配置')
    return
  }
  if (!selectedSessionId.value) {
    ElMessage.warning('请选择目标 Session')
    return
  }
  emit('submit', localYaml.value, selectedSessionId.value)
}

// 取消
const handleClose = () => {
  emit('close')
}

// 初始化
watch(
  () => crewStore.yamlEditorVisible,
  async (visible) => {
    if (visible) {
      // 加载 Session 列表
      try {
        await sessionStore.fetchSessions()
        sessionList.value = sessionStore.sessions
        if (sessionList.value.length > 0) {
          selectedSessionId.value = sessionList.value[0].session_id
        }
      } catch {
        console.error('Failed to load sessions')
      }
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
    <div class="bg-white rounded-xl shadow-2xl w-[90vw] h-[85vh] flex flex-col overflow-hidden">
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-6 py-4 border-b bg-gray-50">
        <div class="flex items-center gap-3">
          <el-icon class="text-blue-600 text-xl"><Edit /></el-icon>
          <h2 class="text-lg font-bold text-gray-900">编排配置编辑器</h2>
        </div>
        <div class="flex items-center gap-3">
          <el-tag v-if="isValid" type="success" effect="dark">校验通过</el-tag>
          <el-tag v-else-if="yamlError" type="danger" effect="dark">配置有误</el-tag>
          <el-button @click="handleClose">取消</el-button>
          <el-button type="primary" :loading="crewStore.submitting" @click="handleSubmit">
            提交执行
          </el-button>
        </div>
      </div>

      <div class="flex flex-1 overflow-hidden">
        <!-- 左侧工具栏 -->
        <div class="w-56 border-r bg-gray-50 p-4 flex flex-col gap-4 overflow-y-auto">
          <!-- 模板选择 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-2">预置模板</label>
            <div class="flex flex-col gap-2">
              <el-button
                :type="selectedTemplate === 'debate' ? 'primary' : 'default'"
                size="small"
                @click="selectTemplate('debate')"
              >
                圆桌辩论
              </el-button>
              <el-button
                :type="selectedTemplate === 'deep-research' ? 'primary' : 'default'"
                size="small"
                @click="selectTemplate('deep-research')"
              >
                深度研究
              </el-button>
              <el-button
                :type="selectedTemplate === 'code-review' ? 'primary' : 'default'"
                size="small"
                @click="selectTemplate('code-review')"
              >
                代码审查
              </el-button>
            </div>
          </div>

          <!-- Session 选择 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-2">目标 Session</label>
            <el-select
              v-model="selectedSessionId"
              placeholder="选择 Session"
              style="width: 100%"
            >
              <el-option
                v-for="s in sessionList"
                :key="s.session_id"
                :label="s.description || s.session_id.slice(0, 12) + '...'"
                :value="s.session_id"
              />
            </el-select>
          </div>

          <!-- 操作按钮 -->
          <div class="flex flex-col gap-2 mt-auto">
            <el-button
              :loading="isValidating"
              :icon="Check"
              @click="handleValidate"
            >
              校验配置
            </el-button>
          </div>
        </div>

        <!-- 编辑器区域 -->
        <div class="flex-1 flex">
          <!-- YAML 编辑器 -->
          <div class="flex-1 flex flex-col">
            <div class="flex items-center justify-between px-4 py-2 bg-gray-100 border-b text-sm text-gray-500">
              <span>YAML 配置 ({{ lineCount }} 行)</span>
              <span class="text-xs">支持 YAML 1.2 格式</span>
            </div>
            <textarea
              v-model="localYaml"
              class="flex-1 w-full p-4 font-mono text-sm leading-relaxed border-0 resize-none focus:outline-none"
              placeholder="在此输入或粘贴 Crew YAML 配置..."
              spellcheck="false"
            />
          </div>

          <!-- 错误面板 -->
          <div
            v-if="yamlError"
            class="w-72 border-l bg-red-50 p-4 overflow-y-auto"
          >
            <div class="flex items-center gap-2 text-red-600 font-medium mb-3">
              <el-icon><Warning /></el-icon>
              <span>校验错误</span>
            </div>
            <pre class="text-xs text-red-700 whitespace-pre-wrap">{{ yamlError }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
textarea {
  tab-size: 2;
  line-height: 1.6;
}
</style>
