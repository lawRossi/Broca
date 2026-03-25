import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/sessions',
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/Chat.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/chat/:session_id?',
    name: 'ChatWithSession',
    component: () => import('@/views/Chat.vue'),
    props: (route) => ({ sessionId: route.params.session_id }),
    meta: { requiresAuth: true }
  },
  {
    path: '/home',
    name: 'Home',
    component: () => import('@/views/Home.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/sessions',
    name: 'Sessions',
    component: () => import('@/views/Sessions.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/jobs',
    name: 'Jobs',
    component: () => import('@/views/Jobs.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/files',
    name: 'Files',
    component: () => import('@/views/Files.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/auth',
    name: 'Auth',
    component: () => import('@/views/Auth.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/auth/callback',
    name: 'AuthCallback',
    component: () => import('@/views/AuthCallback.vue'),
    meta: { requiresAuth: false }
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL || '/'),
  routes,
})

// 全局路由守卫
router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()
  
  // 初始化用户状态
  await userStore.init()
  
  // 检查路由是否需要认证
  if (to.meta.requiresAuth) {
    if (userStore.isLoggedIn) {
      // 用户已登录，允许访问
      next()
    } else {
      // 用户未登录，重定向到登录页面
      next('/auth')
    }
  } else {
    // 不需要认证的路由，直接允许访问
    next()
  }
})

export default router
