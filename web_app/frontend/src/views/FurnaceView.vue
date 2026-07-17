<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { api, ApiError } from '@/api/client'
import { useContextStore } from '@/stores/context'
import type { SeriesResponse } from '@/types/api'
import EChart from '@/components/EChart.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatePanel from '@/components/StatePanel.vue'

const context = useContextStore()
const { datasetId, scopeQuery, availableFurnaces, furnaces } = storeToRefs(context)
const ranking = ref<SeriesResponse | null>(null)
const detail = ref<SeriesResponse | null>(null)
const selected = ref('')
const loading = ref(false)
const error = ref('')

const rankingOption = computed(() => {
  const rows = [...(ranking.value?.rows || [])].slice(0, 30).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 100, right: 42, top: 18, bottom: 32 },
    xAxis: { type: 'value', name: 'kg/h', splitLine: { lineStyle: { color: '#e7e9e5' } } },
    yAxis: { type: 'category', data: rows.map((row) => row.furnace), axisTick: { show: false } },
    series: [{ type: 'bar', data: rows.map((row) => ({ value: row.weighted_yield, itemStyle: { color: row.furnace === selected.value ? '#bd7625' : '#167875' } })), barWidth: 12, itemStyle: { borderRadius: [0, 4, 4, 0] } }],
  }
})

const detailOption = computed(() => {
  const rows = detail.value?.rows || []
  const categories = rows.map((row) => {
    const date = String(row.production_date).slice(5)
    return row.shift_name ? `${date} ${String(row.shift_name)}` : date
  })
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, left: 0 },
    grid: { left: 58, right: 58, top: 48, bottom: 42 },
    xAxis: { type: 'category', data: categories, axisLabel: { hideOverlap: true } },
    yAxis: [{ type: 'value', name: 'kg / h', splitLine: { lineStyle: { color: '#e7e9e5' } } }, { type: 'value', name: 'kg/h', splitLine: { show: false } }],
    series: [
      { name: '产量', type: 'bar', data: rows.map((row) => row.total_output), itemStyle: { color: '#76a9a2' }, barMaxWidth: 18 },
      { name: '加权产率', type: 'line', yAxisIndex: 1, data: rows.map((row) => row.weighted_yield), smooth: 0.25, lineStyle: { width: 2, color: '#bd7625' }, itemStyle: { color: '#bd7625' } },
      { name: '故障时长', type: 'line', data: rows.map((row) => row.fault_hours), lineStyle: { type: 'dashed', color: '#b8433e' }, itemStyle: { color: '#b8433e' } },
    ],
  }
})

async function loadRanking() {
  if (!datasetId.value) return
  loading.value = true; error.value = ''
  try {
    ranking.value = await api.ranking({ ...scopeQuery.value, metric: 'weighted_yield', limit: '100' })
    if (!selected.value) selected.value = furnaces.value[0] || String(ranking.value.rows[0]?.furnace || availableFurnaces.value[0] || '')
    if (selected.value) await loadDetail()
  } catch (caught) { error.value = caught instanceof ApiError ? caught.message : '炉号数据加载失败' }
  finally { loading.value = false }
}

async function loadDetail() {
  if (!selected.value) return
  detail.value = await api.furnace(selected.value, scopeQuery.value)
}

function selectFromRanking(params: { name?: string }) {
  if (params.name) { selected.value = params.name; void loadDetail() }
}

watch(scopeQuery, () => void loadRanking(), { deep: true, immediate: true })
watch(selected, () => void loadDetail())
</script>

<template>
  <div class="view furnace-view">
    <PageHeader eyebrow="FURNACE EXPLORER" title="炉号分析" description="在相同口径下比较炉号表现，并沿时间追踪产量、产率与停机变化。">
      <label class="inline-search"><span>快速定位炉号</span><el-select v-model="selected" filterable placeholder="输入炉号" @change="loadDetail"><el-option v-for="item in availableFurnaces" :key="item" :label="item" :value="item" /></el-select></label>
    </PageHeader>
    <div v-if="loading" class="skeleton-stack"><el-skeleton :rows="12" animated /></div>
    <StatePanel v-else-if="!datasetId" title="请先选择数据版本" />
    <StatePanel v-else-if="error" tone="error" title="炉号分析加载失败" :description="error"><el-button type="primary" @click="loadRanking">重试</el-button></StatePanel>
    <template v-else-if="ranking">
      <section class="furnace-summary" v-if="detail">
        <div><p>当前炉号</p><strong>{{ selected }}</strong><span>{{ (detail.metadata.production_lines as string[] || []).join(' / ') }}</span></div>
        <div><p>累计产量</p><strong>{{ Number((detail.metadata.summary as Record<string, number>)?.total_output || 0).toLocaleString() }}</strong><span>kg</span></div>
        <div><p>加权产率</p><strong>{{ (detail.metadata.summary as Record<string, number>)?.weighted_yield || '—' }}</strong><span>kg/h</span></div>
        <div><p>故障时长</p><strong>{{ (detail.metadata.summary as Record<string, number>)?.fault_hours || 0 }}</strong><span>h</span></div>
      </section>
      <div class="furnace-grid">
        <EChart title="炉号加权产率对比" filename="炉号对比" :option="rankingOption" height="650px">
          <el-table :data="ranking.rows" max-height="360" @row-click="(row: Record<string, unknown>) => selected = String(row.furnace)"><el-table-column prop="furnace" label="炉号" /><el-table-column prop="production_line" label="产线" /><el-table-column prop="weighted_yield" label="加权产率" /><el-table-column prop="fault_hours" label="故障时长" /></el-table>
        </EChart>
        <div class="furnace-detail-column">
          <EChart v-if="detail" :title="`${selected} ${detail.grain === 'shift' ? '班次' : '炉日'}表现`" :filename="`${selected}_表现`" :option="detailOption" height="420px">
            <el-table :data="detail.rows" max-height="320"><el-table-column prop="production_date" label="日期" /><el-table-column v-if="detail.grain === 'shift'" prop="shift_name" label="班次" /><el-table-column prop="total_output" label="产量" /><el-table-column prop="weighted_yield" label="加权产率" /><el-table-column prop="fault_hours" label="故障" /></el-table>
          </EChart>
          <section class="definition-card"><p class="eyebrow">METRIC NOTE</p><h2>口径说明</h2><p>炉号产率使用筛选范围内成对有效记录的产量合计除以反应时间合计，不对班次产率做简单平均。炉日视图是只读聚合层。</p></section>
        </div>
      </div>
    </template>
  </div>
</template>
