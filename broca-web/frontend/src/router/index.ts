import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/sessions',
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/Chat.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/chat/:session_id?',
    name: 'ChatWithSession',
    component: () => import('@/views/Chat.vue'),
    props: (route) => ({ sessionId: route.params.session_id }),
    meta: { requiresAuth: true },
  },
  {
    path: '/home',
    name: 'Home',
    component: () => import('@/views/Home.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/sessions',
    name: 'Sessions',
    component: () => import('@/views/Sessions.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/jobs',
    name: 'Jobs',
    component: () => import('@/views/Jobs.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/Tasks.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/files',
    name: 'Files',
    component: () => import('@/views/Files.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/auth',
    name: 'Auth',
    component: () => import('@/views/Auth.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/auth/callback',
    name: 'AuthCallback',
    component: () => import('@/views/AuthCallback.vue'),
    meta: { requiresAuth: false },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL || '/'),
  routes,
})

export default router
