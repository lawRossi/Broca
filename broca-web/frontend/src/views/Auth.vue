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
  <div class="min-h-screen flex items-center justify-center bg-gray-50 p-4">
    <div class="w-full max-w-lg">
      <div class="card hover-lift">
        <div class="card-header">
          <h2 class="text-3xl font-bold text-center text-gray-900">Broca</h2>
          <p class="text-center text-gray-500 text-sm mt-2">
            账户在安装时创建
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

<style scoped></style>
