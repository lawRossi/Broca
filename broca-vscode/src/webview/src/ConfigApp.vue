<script setup lang="ts">
import { ref, reactive } from 'vue'
import ClientConfigPanel from './components/settings/ClientConfigPanel.vue'
import GeneralConfigPanel from './components/settings/GeneralConfigPanel.vue'
import LLMConfigPanel from './components/settings/LLMConfigPanel.vue'
import ToolPermissionPanel from './components/settings/ToolPermissionPanel.vue'
import McpConfigPanel from './components/settings/McpConfigPanel.vue'

import './components/settings/settings.css'

type TabKey = 'client' | 'general' | 'llm' | 'toolPermission' | 'mcp'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'client', label: '客户端设置' },
  { key: 'general', label: '基础配置' },
  { key: 'llm', label: 'LLM 配置' },
  { key: 'toolPermission', label: '工具权限' },
  { key: 'mcp', label: 'MCP 配置' },
]

const activeTab = ref<TabKey>('client')
const activatedTabs = reactive<Record<string, boolean>>({ client: true })

function switchTab(key: TabKey) {
  activeTab.value = key
  activatedTabs[key] = true
}
</script>

<template>
  <div class="settings-container">
    <h1 class="title">Broca Settings</h1>

    <!-- Tab bar -->
    <div class="tab-bar">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Panels: lazy-mount on first activation, keep mounted via v-show -->
    <ClientConfigPanel v-if="activatedTabs.client" v-show="activeTab === 'client'" />
    <GeneralConfigPanel v-if="activatedTabs.general" v-show="activeTab === 'general'" />
    <LLMConfigPanel v-if="activatedTabs.llm" v-show="activeTab === 'llm'" />
    <ToolPermissionPanel v-if="activatedTabs.toolPermission" v-show="activeTab === 'toolPermission'" />
    <McpConfigPanel v-if="activatedTabs.mcp" v-show="activeTab === 'mcp'" />
  </div>
</template>

<style>
.title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-primary);
}
</style>
