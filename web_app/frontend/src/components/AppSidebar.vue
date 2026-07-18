<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const { user } = storeToRefs(auth)
const collapsed = ref(localStorage.getItem('cnt-sidebar') === 'collapsed')
const items = [
  { to: '/', label: '生产总览', short: '总', mark: 'M4 5h16v4H4zm0 6h7v8H4zm9 0h7v8h-7z' },
  { to: '/furnaces', label: '炉号分析', short: '炉', mark: 'M7 3h10v4l3 4v10H4V11l3-4zm2 6-2 3v6h10v-6l-2-3z' },
  { to: '/diagnostics', label: '异常与故障', short: '警', mark: 'M12 3 2.8 20h18.4zm0 5v5m0 3v1' },
  { to: '/reports', label: '报表中心', short: '报', mark: 'M6 3h9l3 3v15H6zm3 7h6m-6 4h6m-6 4h4' },
  { to: '/data', label: '数据管理', short: '数', mark: 'M4 6c0-2 16-2 16 0v12c0 2-16 2-16 0zm0 0c0 2 16 2 16 0M4 12c0 2 16 2 16 0' },
]

function toggle() {
  collapsed.value = !collapsed.value
  localStorage.setItem('cnt-sidebar', collapsed.value ? 'collapsed' : 'expanded')
}
</script>

<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': collapsed }">
    <div class="brand">
      <div class="brand__symbol" aria-hidden="true"><i /><i /><i /></div>
      <div class="brand__text"><strong>生产分析台</strong><span>CNT WORKBENCH</span></div>
    </div>
    <nav class="primary-nav" aria-label="主要导航">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        :class="{ active: item.to === '/' ? route.path === '/' : route.path.startsWith(item.to) }"
        :title="collapsed ? item.label : undefined"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="item.mark" /></svg>
        <span>{{ collapsed ? item.short : item.label }}</span>
      </RouterLink>
    </nav>
    <div v-if="user" class="sidebar-session" :title="`${user.display_name}（${user.username}）`">
      <span class="sidebar-session__avatar">{{ user.display_name.slice(0, 1).toUpperCase() }}</span>
      <span class="sidebar-session__identity"><strong>{{ user.display_name }}</strong><small>@{{ user.username }}</small></span>
      <button type="button" aria-label="退出登录" title="退出登录" @click="auth.logout">退出</button>
    </div>
    <div class="sidebar__foot">
      <span class="offline-dot" /><span class="sidebar__offline">厂内离线模式</span>
      <button type="button" class="collapse-button" :aria-label="collapsed ? '展开导航' : '收起导航'" @click="toggle">
        {{ collapsed ? '›' : '‹' }}
      </button>
    </div>
  </aside>
</template>
