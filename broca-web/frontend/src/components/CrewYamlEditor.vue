<script setup lang="ts">
/**
 * Crew YAML 编辑器组件
 * 支持语法高亮、实时校验、模板选择、加载已有配置
 */
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCrewStore } from '@/stores/crew'
import { useSessionStore } from '@/stores/session'
import type { CrewConfigFile } from '@/api/crew'
import { Document, Edit, Check, Warning, FolderOpened } from '@element-plus/icons-vue'

const props = withDefaults(
  defineProps<{
    initialYaml?: string
    configFiles?: CrewConfigFile[]
    activeWorkspace?: string
    fixedSessionId?: string // 当从编排管理页进入时，session 固定
  }>(),
  {
    initialYaml: '',
    configFiles: () => [],
    activeWorkspace: '',
    fixedSessionId: '',
  }
)

const emit = defineEmits<{
  close: []
  submit: [yaml: string, sessionId: string]
  loadConfig: [cfg: CrewConfigFile]
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
const localYaml = ref(props.initialYaml || '')
const selectedTemplate = ref<string>('')
const selectedSessionId = ref(props.fixedSessionId || '')
const sessionList = ref<Array<{ session_id: string; description?: string }>>([])
const isValidating = ref(false)
const isValid = ref(false)
const yamlError = ref('')
const activeSection = ref<'templates' | 'configs'>('templates')

// 编辑器行数
const lineCount = computed(() => localYaml.value.split('\n').length)

// 如果绑定了固定 session，直接使用
watch(
  () => props.fixedSessionId,
  (newVal) => {
    if (newVal) {
      selectedSessionId.value = newVal
    }
  },
  { immediate: true }
)

// 监听 initialYaml prop 变化
watch(
  () => props.initialYaml,
  (newVal) => {
    if (newVal) {
      localYaml.value = newVal
      isValid.value = false
      yamlError.value = ''
      selectedTemplate.value = ''
    }
  },
  { immediate: true }
)

// 选择模板
const selectTemplate = (templateId: string) => {
  selectedTemplate.value = templateId
  if (templateId && templates[templateId as keyof typeof templates]) {
    localYaml.value = templates[templateId as keyof typeof templates]
    isValid.value = false
    yamlError.value = ''
  }
}

// 从已有配置加载
const handleLoadConfigClick = async (cfg: CrewConfigFile) => {
  await crewStore.loadConfigIntoEditor(cfg.filename, props.activeWorkspace)
  localYaml.value = crewStore.yamlContent
  isValid.value = false
  yamlError.value = ''
  selectedTemplate.value = ''
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

// 保存
const isEditingExisting = computed(() => !!crewStore.currentEditedFilePath)

const handleSave = async () => {
  if (!localYaml.value.trim()) {
    ElMessage.warning('请输入 YAML 配置')
    return
  }

  if (crewStore.currentEditedFilePath) {
    // 编辑已有文件 → 直接保存回写
    await crewStore.saveConfigFile(localYaml.value)
  } else {
    // 新建文件 → 弹窗让用户输入文件名
    try {
      const { value: filename } = await ElMessageBox.prompt('请输入编排配置文件名（.yaml）', '保存为新文件', {
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputValue: 'crew.yaml',
        inputPattern: /^[\w-]+\.(yaml|yml)$/,
        inputErrorMessage: '文件名必须以 .yaml 或 .yml 结尾',
      })
      if (filename && crewStore.activeWorkspace) {
        crewStore.currentEditedFilename = filename
        await crewStore.saveConfigFile(localYaml.value)
      }
    } catch {
      // 用户取消，不处理
    }
  }
}

// 取消
const handleClose = () => {
  emit('close')
}

// 初始化
onMounted(async () => {
  // 如果已经绑定了固定 session，不需要加载列表
  if (props.fixedSessionId) {
    selectedSessionId.value = props.fixedSessionId
    return
  }

  // 否则才加载 Session 列表供选择
  try {
    await sessionStore.fetchSessions()
    sessionList.value = sessionStore.sessions
    if (sessionList.value.length > 0 && !selectedSessionId.value) {
      selectedSessionId.value = sessionList.value[0].session_id
    }
  } catch {
    console.error('Failed to load sessions')
  }
})
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-0 sm:p-4">
    <div class="bg-white shadow-2xl flex flex-col overflow-hidden w-full h-full sm:rounded-xl sm:w-[90vw] sm:h-[85vh]">
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-4 py-3 sm:px-6 sm:py-4 border-b bg-gray-50">
        <div class="flex items-center gap-2 min-w-0">
          <el-icon class="text-blue-600 text-lg sm:text-xl flex-shrink-0">
            <Edit />
          </el-icon>
          <h2 class="text-sm sm:text-lg font-bold text-gray-900 truncate">编排配置编辑器</h2>
        </div>
        <div class="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          <el-tag v-if="isValid" type="success" effect="dark" size="small" class="hidden sm:inline-flex">
            校验通过
          </el-tag>
          <el-tag v-else-if="yamlError" type="danger" effect="dark" size="small" class="hidden sm:inline-flex">
            配置有误
          </el-tag>
          <el-button size="small" @click="handleClose"> 取消 </el-button>
          <el-button size="small" type="primary" :loading="crewStore.saving" @click="handleSave"> 保存 </el-button>
        </div>
      </div>

      <div class="flex flex-1 overflow-hidden flex-col sm:flex-row">
        <!-- 左侧工具栏 -->
        <div class="border-b sm:border-b-0 sm:border-r bg-gray-50 overflow-y-auto sm:w-48 lg:w-60 flex-shrink-0">
          <div class="p-3 sm:p-4 flex flex-col gap-3">
            <!-- 切换标签：模板 / 已有配置 -->
            <div class="flex border-b pb-2">
              <el-button
                :type="activeSection === 'templates' ? 'primary' : 'default'"
                size="small"
                style="flex: 1"
                @click="activeSection = 'templates'"
              >
                模板
              </el-button>
              <el-button
                :type="activeSection === 'configs' ? 'primary' : 'default'"
                size="small"
                style="flex: 1"
                @click="activeSection = 'configs'"
              >
                已有配置
              </el-button>
            </div>

            <!-- 模板选择 -->
            <div v-if="activeSection === 'templates'">
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

            <!-- 已有配置列表 -->
            <div v-if="activeSection === 'configs'">
              <label class="block text-sm font-medium text-gray-700 mb-2">
                已有编排配置
                <span v-if="configFiles.length" class="text-gray-400 font-normal">({{ configFiles.length }})</span>
              </label>
              <div v-if="configFiles.length === 0" class="text-xs text-gray-400 py-4 text-center">
                <p>暂无已有配置</p>
                <p class="mt-1">请先在「已有编排」Tab 中选择工作空间</p>
              </div>
              <div v-else class="flex flex-col gap-2">
                <div
                  v-for="cfg in configFiles"
                  :key="cfg.filename"
                  class="bg-white rounded border p-2 cursor-pointer hover:border-blue-300 transition-colors"
                  @click="handleLoadConfigClick(cfg)"
                >
                  <div class="text-xs font-medium text-gray-800 truncate">
                    {{ cfg.name || cfg.filename }}
                  </div>
                  <div class="flex items-center gap-2 mt-1">
                    <el-tag
                      v-if="cfg.orchestrator_type"
                      size="small"
                      type="info"
                      effect="plain"
                      style="font-size: 10px; height: 18px; line-height: 16px"
                    >
                      {{ cfg.orchestrator_type }}
                    </el-tag>
                    <el-tag
                      v-if="cfg.parse_error"
                      size="small"
                      type="danger"
                      effect="light"
                      style="font-size: 10px; height: 18px; line-height: 16px"
                    >
                      错误
                    </el-tag>
                  </div>
                  <div class="text-xs text-gray-400 mt-1 truncate">
                    {{ cfg.filename }}
                  </div>
                </div>
              </div>
            </div>

            <!-- Session 选择（仅当没有固定 session 时显示） -->
            <div v-if="!fixedSessionId" class="mt-auto pt-2 border-t">
              <label class="block text-sm font-medium text-gray-700 mb-2">目标 Session</label>
              <el-select v-model="selectedSessionId" placeholder="选择 Session" style="width: 100%">
                <el-option
                  v-for="s in sessionList"
                  :key="s.session_id"
                  :label="s.description || s.session_id.slice(0, 12) + '...'"
                  :value="s.session_id"
                />
              </el-select>
            </div>

            <!-- 固定 session 提示 -->
            <div v-else class="mt-auto pt-2 border-t">
              <label class="block text-sm font-medium text-gray-700 mb-2">目标 Session</label>
              <el-tag type="primary" effect="plain" style="width: 100%; justify-content: center">
                {{ fixedSessionId.slice(0, 12) }}...
              </el-tag>
            </div>

            <!-- 操作按钮 -->
            <div class="flex flex-col gap-2">
              <el-button :loading="isValidating" :icon="Check" @click="handleValidate"> 校验配置 </el-button>
            </div>
          </div>
        </div>

        <!-- 编辑器区域 -->
        <div class="flex-1 flex flex-col sm:flex-row">
          <!-- YAML 编辑器 -->
          <div class="flex-1 flex flex-col min-h-0">
            <div class="flex items-center justify-between px-4 py-2 bg-gray-100 border-b text-sm text-gray-500">
              <span>YAML 配置 ({{ lineCount }} 行)</span>
              <span class="text-xs">支持 YAML 1.2 格式</span>
            </div>
            <textarea
              v-model="localYaml"
              class="flex-1 w-full p-3 sm:p-4 font-mono text-xs sm:text-sm leading-relaxed border-0 resize-none focus:outline-none"
              placeholder="在此输入或粘贴 Crew YAML 配置..."
              spellcheck="false"
            />
          </div>

          <!-- 错误面板（桌面端右侧，移动端底部） -->
          <div
            v-if="yamlError"
            class="bg-red-50 overflow-y-auto sm:w-72 sm:border-l max-h-32 sm:max-h-none border-t sm:border-t-0"
          >
            <div class="flex items-center gap-2 text-red-600 font-medium px-4 py-2 sm:px-4 sm:py-3">
              <el-icon><Warning /></el-icon>
              <span>校验错误</span>
            </div>
            <pre class="text-xs text-red-700 whitespace-pre-wrap px-4 pb-3 sm:px-4 sm:pb-4">{{ yamlError }}</pre>
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

@media (max-width: 640px) {
  :deep(.el-button) {
    min-height: 36px;
    min-width: 36px;
  }

  :deep(*) {
    -webkit-tap-highlight-color: transparent;
  }

  :deep(input),
  :deep(textarea),
  :deep(.el-input__inner) {
    font-size: 16px;
  }

  textarea {
    font-size: 13px;
  }
}
</style>
