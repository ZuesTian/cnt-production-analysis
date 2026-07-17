import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { LocationQuery, Router } from 'vue-router'
import { api } from '@/api/client'
import type { DatasetSummary, FilterOptions, Grain } from '@/types/api'

export const useContextStore = defineStore('context', () => {
  const datasets = ref<DatasetSummary[]>([])
  const filters = ref<FilterOptions | null>(null)
  const datasetId = ref('')
  const grain = ref<Grain>('furnace_day')
  const productionLines = ref<string[]>([])
  const furnaces = ref<string[]>([])
  const dateRange = ref<[string, string] | []>([])
  const loading = ref(false)
  const initialized = ref(false)

  const activeDataset = computed(() => datasets.value.find((item) => item.id === datasetId.value) || null)
  const availableFurnaces = computed(() => {
    if (!filters.value) return []
    if (!productionLines.value.length) return filters.value.furnaces
    return [...new Set(productionLines.value.flatMap((line) => filters.value?.furnaces_by_line[line] || []))].sort()
  })
  const scopeQuery = computed<Record<string, string | string[] | undefined>>(() => ({
    dataset_id: datasetId.value || undefined,
    grain: grain.value,
    production_lines: productionLines.value,
    furnaces: furnaces.value,
    date_from: dateRange.value[0],
    date_to: dateRange.value[1],
  }))

  function hydrate(query: LocationQuery) {
    datasetId.value = typeof query.dataset === 'string' ? query.dataset : datasetId.value
    grain.value = query.grain === 'shift' ? 'shift' : 'furnace_day'
    productionLines.value = typeof query.lines === 'string' ? query.lines.split(',').filter(Boolean) : []
    furnaces.value = typeof query.furnaces === 'string' ? query.furnaces.split(',').filter(Boolean) : []
    if (typeof query.from === 'string' && typeof query.to === 'string') dateRange.value = [query.from, query.to]
  }

  async function initialize(query: LocationQuery) {
    if (initialized.value) return
    hydrate(query)
    await refreshDatasets()
    initialized.value = true
  }

  async function refreshDatasets() {
    loading.value = true
    try {
      datasets.value = await api.datasets()
      if (!datasetId.value || !datasets.value.some((item) => item.id === datasetId.value)) {
        datasetId.value = datasets.value.find((item) => item.status === 'published')?.id
          || datasets.value.find((item) => item.kind === 'temporary' && item.status === 'ready')?.id
          || ''
      }
      await refreshFilters()
    } finally {
      loading.value = false
    }
  }

  async function refreshFilters() {
    if (!datasetId.value) {
      filters.value = null
      return
    }
    filters.value = await api.filters(datasetId.value)
    productionLines.value = productionLines.value.filter((line) => filters.value?.production_lines.includes(line))
    furnaces.value = furnaces.value.filter((furnace) => filters.value?.furnaces.includes(furnace))
  }

  async function selectDataset(id: string) {
    datasetId.value = id
    productionLines.value = []
    furnaces.value = []
    dateRange.value = []
    await refreshFilters()
  }

  function syncUrl(router: Router) {
    const query: Record<string, string> = {}
    if (datasetId.value) query.dataset = datasetId.value
    if (grain.value !== 'furnace_day') query.grain = grain.value
    if (productionLines.value.length) query.lines = productionLines.value.join(',')
    if (furnaces.value.length) query.furnaces = furnaces.value.join(',')
    if (dateRange.value.length === 2) {
      query.from = dateRange.value[0]
      query.to = dateRange.value[1]
    }
    void router.replace({ query })
  }

  function resetScope() {
    productionLines.value = []
    furnaces.value = []
    dateRange.value = []
    grain.value = 'furnace_day'
  }

  return {
    datasets, filters, datasetId, grain, productionLines, furnaces, dateRange,
    loading, initialized, activeDataset, availableFurnaces, scopeQuery,
    hydrate, initialize, refreshDatasets, refreshFilters, selectDataset, syncUrl, resetScope,
  }
})
