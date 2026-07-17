import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'

const history = import.meta.env.VITE_ROUTER_MODE === 'hash'
  ? createWebHashHistory(import.meta.env.BASE_URL)
  : createWebHistory(import.meta.env.BASE_URL)

const router = createRouter({
  history,
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '生产总览' } },
        { path: 'furnaces', name: 'furnaces', component: () => import('@/views/FurnaceView.vue'), meta: { title: '炉号分析' } },
        { path: 'diagnostics', name: 'diagnostics', component: () => import('@/views/DiagnosticsView.vue'), meta: { title: '异常与故障' } },
        { path: 'reports', name: 'reports', component: () => import('@/views/ReportsView.vue'), meta: { title: '报表中心', desktopOnly: true } },
        { path: 'data', name: 'data', component: () => import('@/views/DataManagementView.vue'), meta: { title: '数据管理', desktopOnly: true } },
      ],
    },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || '工作台')} · 碳纳米管生产分析`
})

export default router
