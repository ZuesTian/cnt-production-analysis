import { computed, onBeforeUnmount, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { JobStatus } from '@/types/api'

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<JobStatus[]>([])
  let timer: number | undefined
  const activeJobs = computed(() => jobs.value.filter((job) => ['queued', 'running'].includes(job.status)))

  async function refresh() {
    jobs.value = await api.jobs()
    if (activeJobs.value.length) startPolling()
    else stopPolling()
  }

  async function waitFor(id: string, timeoutMs = 120_000): Promise<JobStatus> {
    const started = Date.now()
    while (Date.now() - started < timeoutMs) {
      const job = await api.job(id)
      jobs.value = [job, ...jobs.value.filter((item) => item.id !== id)]
      if (['completed', 'failed', 'cancelled'].includes(job.status)) return job
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    throw new Error('后台作业等待超时')
  }

  function startPolling() {
    if (timer) return
    timer = window.setInterval(() => void refresh(), 1000)
  }

  function stopPolling() {
    if (timer) window.clearInterval(timer)
    timer = undefined
  }

  onBeforeUnmount(stopPolling)
  return { jobs, activeJobs, refresh, waitFor, startPolling, stopPolling }
})
