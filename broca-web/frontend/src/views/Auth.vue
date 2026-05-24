<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores'
import type { LoginForm } from '@/api/user'

const router = useRouter()
const userStore = useUserStore()

const loginForm = ref<LoginForm>({
  username: '',
  password: '',
})

const loading = ref(false)

const handleLogin = async () => {
  loading.value = true
  try {
    const success = await userStore.login(loginForm.value)
    if (success) {
      router.push('/')
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await userStore.init()
  if (userStore.isLoggedIn) {
    router.push('/')
  }
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950 p-4">
    <div class="w-full max-w-lg">
      <div class="card hover-lift">
        <div class="card-header">
          <h2 class="text-3xl font-bold text-center text-gray-900 dark:text-gray-100">Broca</h2>
          <p class="text-center text-gray-500 dark:text-gray-400 text-sm mt-2">
            账户由管理员在安装时创建，请联系管理员获取登录凭据
          </p>
        </div>

        <div class="card-body">
          <div class="space-y-6">
            <el-form :model="loginForm" label-position="top" class="space-y-4">
              <div class="form-group">
                <label class="form-label">用户名</label>
                <el-input v-model="loginForm.username" placeholder="请输入用户名" class="form-input" />
              </div>

              <div class="form-group">
                <label class="form-label">密码</label>
                <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" class="form-input" @keyup.enter="handleLogin" />
              </div>
            </el-form>

            <button
              class="btn btn-primary w-full"
              :disabled="loading"
              @click="handleLogin"
            >
              {{ loading ? '登录中...' : '登录' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@media (prefers-color-scheme: dark) {
  /* 页面背景不要太深 */
  .bg-gray-50.dark\:bg-gray-950 {
    background-color: #0f172a !important;
  }

  /* 卡片更明显 - 浅色背景 + 边框 + 阴影 */
  :deep(.card) {
    background-color: #1e293b !important;
    border-color: #475569 !important;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4) !important;
  }

  :deep(.card-header) {
    background-color: #334155 !important;
    border-bottom-color: #475569 !important;
  }

  :deep(.el-input__wrapper) {
    background-color: #0f172a !important;
    box-shadow: 0 0 0 1px #475569 inset !important;
  }
  :deep(.el-input__inner) {
    color: #f1f5f9 !important;
  }
  :deep(.el-input__inner::placeholder) {
    color: #64748b !important;
  }
}
</style>
