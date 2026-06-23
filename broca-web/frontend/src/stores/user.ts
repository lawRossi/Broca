import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { type LoginForm, type UserInfo, userApi } from '@/api/user'
import router from '@/router'

export const useUserStore = defineStore('user', () => {
  // 状态
  const token = ref<string | null>(localStorage.getItem('token'))
  const userId = ref<string | null>(localStorage.getItem('user_id'))
  const username = ref<string | null>(localStorage.getItem('username'))
  const isLoggedIn = ref<boolean>(!!token.value)
  const userInfo = ref<UserInfo | null>(null)

  // 注册功能已移除：请在安装时通过 scripts/setup_admin.py 创建账户

  // 登录
  const login = async (loginForm: LoginForm) => {
    try {
      if (!loginForm.username || !loginForm.password) {
        ElMessage.error('请填写用户名和密码')
        return false
      }

      const result = await userApi.login(loginForm)
      token.value = result.token
      userId.value = result.user_id
      username.value = result.username
      isLoggedIn.value = true

      localStorage.setItem('token', result.token)
      localStorage.setItem('user_id', result.user_id)
      localStorage.setItem('username', result.username)

      userInfo.value = await userApi.getUserInfo().catch(() => null)
      ElMessage.success('登录成功')
      return true
    } catch (error: any) {
      const msg = error?.response?.data?.detail || error.message || '登录失败'
      ElMessage.error(msg)
      return false
    }
  }

  // 登出
  const logout = async () => {
    token.value = null
    userId.value = null
    username.value = null
    userInfo.value = null
    isLoggedIn.value = false

    localStorage.removeItem('token')
    localStorage.removeItem('user_id')
    localStorage.removeItem('username')
    router.push('/auth')
    ElMessage.success('已登出')
  }

  const fetchUserInfo = async () => {
    try {
      if (!userId.value) return
      if (userInfo.value) return userInfo.value
      userInfo.value = await userApi.getUserInfo()
      return userInfo.value
    } catch (error) {
      console.error('获取用户信息失败:', error)
    }
  }

  const init = async () => {
    console.log('初始化用户信息')
    const savedToken = localStorage.getItem('token')
    if (savedToken) {
      token.value = savedToken
      userId.value = localStorage.getItem('user_id')
      username.value = localStorage.getItem('username')
      isLoggedIn.value = true
      try {
        userInfo.value = await userApi.getUserInfo()
      } catch {
        // token 可能过期，但暂时不强制登出
        console.warn('Failed to fetch user info, token may be expired')
      }
    } else {
      // 无 token 时尝试本地自动登录（仅对 localhost 部署生效）
      try {
        const result = await userApi.localLogin()
        token.value = result.token
        userId.value = result.user_id
        username.value = result.username
        isLoggedIn.value = true
        localStorage.setItem('token', result.token)
        localStorage.setItem('user_id', result.user_id)
        localStorage.setItem('username', result.username)
        console.log('本地自动登录成功')
        // 自动登录后获取用户信息
        try {
          userInfo.value = await userApi.getUserInfo()
        } catch {
          console.warn('Failed to fetch local user info')
        }
      } catch {
        // 非本机部署或自动登录失败 → 保持未登录状态
        console.log('本地自动登录不可用，需要手动登录')
        token.value = null
        userId.value = null
        username.value = null
        isLoggedIn.value = false
      }
    }
  }

  return {
    token,
    userId,
    username,
    isLoggedIn,
    userInfo,
    login,
    logout,
    init,
    fetchUserInfo,
  }
})
