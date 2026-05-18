<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
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
const isRegisterMode = ref(false)

const isLoggedIn = computed(() => userStore.isLoggedIn)

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

const handleRegister = async () => {
  loading.value = true
  try {
    const success = await userStore.register(loginForm.value)
    if (success) {
      router.push('/')
    }
  } finally {
    loading.value = false
  }
}

const toggleMode = () => {
  isRegisterMode.value = !isRegisterMode.value
}

onMounted(async () => {
  await userStore.init()
  if (isLoggedIn.value) {
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
          <p class="text-center text-gray-600 mt-2">
            {{ isRegisterMode ? '创建新账户' : '登录到您的账户' }}
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
                <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" class="form-input" />
              </div>
            </el-form>

            <div class="flex flex-col sm:flex-row gap-3">
              <button
                class="btn btn-primary flex-1 sm:flex-none"
                :disabled="loading"
                @click="isRegisterMode ? handleRegister() : handleLogin()"
              >
                {{ loading ? (isRegisterMode ? '注册中...' : '登录中...') : isRegisterMode ? '注册' : '登录' }}
              </button>

              <button class="btn btn-outline flex-1 sm:flex-none btn-hover-fix" @click="toggleMode">
                切换到{{ isRegisterMode ? '登录' : '注册' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
