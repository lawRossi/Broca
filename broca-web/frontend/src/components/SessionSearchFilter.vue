<script setup lang="ts">
import { Search, Plus } from '@element-plus/icons-vue'

interface Props {
  searchKeyword: string
  isLoggedIn: boolean
}

interface Emits {
  (e: 'update:searchKeyword', value: string): void
  (e: 'create'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 搜索处理
const handleSearch = (value: string) => {
  emit('update:searchKeyword', value)
}

// 创建按钮点击
const handleCreate = () => {
  emit('create')
}
</script>

<template>
  <div class="session-search-filter flex flex-col sm:flex-row gap-3">
    <!-- 搜索框 -->
    <el-input :model-value="searchKeyword" placeholder="搜索会话..." clearable class="flex-1" @input="handleSearch">
      <template #prefix>
        <el-icon><Search /></el-icon>
      </template>
    </el-input>
  </div>
</template>
