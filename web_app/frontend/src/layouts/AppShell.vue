<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useContextStore } from '@/stores/context'
import { useJobsStore } from '@/stores/jobs'
import { ApiError } from '@/api/client'
import AppSidebar from '@/components/AppSidebar.vue'
import TopContextBar from '@/components/TopContextBar.vue'

const route = useRoute()
const router = useRouter()
const context = useContextStore()
const jobs = useJobsStore()
const { activeJobs } = storeToRefs(jobs)

function contextChanged() { context.syncUrl(router) }

onMounted(async () => {
  try {
    await context.initialize(route.query)
    context.syncUrl(router)
    await jobs.refresh()
  } catch (caught) {
    if (!(caught instanceof ApiError && caught.status === 401)) throw caught
  }
})

watch(() => route.query.dataset, (value) => {
  if (typeof value === 'string' && value !== context.datasetId) void context.selectDataset(value)
})
</script>

<template>
  <div class="app-shell">
    <AppSidebar />
    <div class="app-column">
      <TopContextBar @change="contextChanged" />
      <div v-if="activeJobs.length" class="job-strip" role="status" aria-live="polite">
        <span class="job-strip__pulse" />
        <strong>{{ activeJobs[0].message }}</strong>
        <el-progress :percentage="activeJobs[0].progress" :stroke-width="5" :show-text="false" />
        <span>{{ activeJobs[0].progress }}%</span>
      </div>
      <main id="main-content" class="workspace" tabindex="-1">
        <RouterView :key="String(route.name)" />
      </main>
    </div>

    <nav class="mobile-nav" aria-label="移动端主要导航">
      <RouterLink to="/"><span aria-hidden="true">▦</span><small>总览</small></RouterLink>
      <RouterLink to="/diagnostics"><span aria-hidden="true">△</span><small>告警</small></RouterLink>
      <RouterLink to="/furnaces"><span aria-hidden="true">◎</span><small>炉号</small></RouterLink>
    </nav>
  </div>
</template>
