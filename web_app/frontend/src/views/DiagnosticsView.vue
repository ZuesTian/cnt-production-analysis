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
const { datasetId, scopeQuery } = storeToRefs(context)
const activeTab = ref('anomalies')
const data = ref<SeriesResponse | null>(null)
const loading = ref(false)
const error = ref('')
const tabs = [
  { value: 'anomalies', label: '规则异常', description: '固定最低产率 + 炉号内 2σ' },
  { value: 'faults', label: '故障告警', description: '按日故障阈值分级' },
  { value: 'yield_heatmap', label: '产率矩阵', description: '炉号 × 日期' },
  { value: 'distribution', label: '分布诊断', description: '班次产率与反应时间' },
]

const title = computed(() => tabs.find((tab) => tab.value === activeTab.value)?.label || '诊断')
const criticalCount = computed(() => data.value?.rows.filter((row) => row.level === 'critical').length || 0)

function histogram(values: number[], bins = 16) {
  if (!values.length) return { labels: [], counts: [] }
  const min = Math.min(...values); const max = Math.max(...values)
  const step = (max - min || 1) / bins
  const counts = Array.from({ length: bins }, () => 0)
  values.forEach((value) => counts[Math.min(bins - 1, Math.floor((value - min) / step))]++)
  return { labels: counts.map((_, index) => `${(min + index * step).toFixed(1)}`), counts }
}

const chartOption = computed(() => {
  const rows = data.value?.rows || []
  if (activeTab.value === 'anomalies') {
    const counts = new Map<string, number>()
    rows.forEach((row) => counts.set(String(row.furnace), (counts.get(String(row.furnace)) || 0) + 1))
    const ranked = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 30).reverse()
    return { tooltip: { trigger: 'axis' }, grid: { left: 95, right: 32, top: 18, bottom: 34 }, xAxis: { type: 'value', name: '异常班次' }, yAxis: { type: 'category', data: ranked.map(([name]) => name) }, series: [{ type: 'bar', data: ranked.map(([, count]) => count), itemStyle: { color: '#bd7625', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 14 }] }
  }
  if (activeTab.value === 'faults') {
    const ranked = [...rows].sort((a, b) => Number(b.fault_time) - Number(a.fault_time)).slice(0, 35).reverse()
    return { tooltip: { trigger: 'axis' }, grid: { left: 95, right: 36, top: 18, bottom: 34 }, xAxis: { type: 'value', name: 'h' }, yAxis: { type: 'category', data: ranked.map((row) => String(row.furnace)) }, series: [{ type: 'bar', data: ranked.map((row) => ({ value: row.fault_time, itemStyle: { color: row.level === 'critical' ? '#b8433e' : row.level === 'warning' ? '#c58a2c' : '#8c9b97' } })), barMaxWidth: 14 }] }
  }
  if (activeTab.value === 'yield_heatmap') {
    const dates = [...new Set(rows.map((row) => String(row.production_date)))].sort()
    const furnaces = [...new Set(rows.map((row) => String(row.furnace)))].sort()
    const dateIndex = new Map(dates.map((value, index) => [value, index])); const furnaceIndex = new Map(furnaces.map((value, index) => [value, index]))
    const values = rows.map((row) => [dateIndex.get(String(row.production_date)), furnaceIndex.get(String(row.furnace)), row.weighted_yield])
    const numeric = rows.map((row) => Number(row.weighted_yield)).filter(Number.isFinite)
    return { tooltip: { position: 'top' }, grid: { left: 95, right: 65, top: 20, bottom: 66 }, xAxis: { type: 'category', data: dates.map((date) => date.slice(5)), axisLabel: { hideOverlap: true } }, yAxis: { type: 'category', data: furnaces }, visualMap: { min: numeric.length ? Math.min(...numeric) : 0, max: numeric.length ? Math.max(...numeric) : 1, calculable: true, orient: 'vertical', right: 0, top: 'middle', inRange: { color: ['#d9e5df', '#87b5ab', '#126a68', '#8c5936'] } }, dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 10 }], series: [{ type: 'heatmap', data: values, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,.25)' } } }] }
  }
  const yields = rows.map((row) => Number(row.weighted_yield)).filter(Number.isFinite)
  const reactions = rows.map((row) => Number(row.reaction_time)).filter(Number.isFinite)
  const yieldHist = histogram(yields); const reactionHist = histogram(reactions)
  return {
    tooltip: { trigger: 'axis' },
    grid: [
      { left: 58, right: 32, top: 34, height: '32%' },
      { left: 58, right: 32, top: '58%', height: '30%' },
    ],
    xAxis: [
      { type: 'category', gridIndex: 0, data: yieldHist.labels, name: '产率区间下限 (kg/h)', axisLabel: { hideOverlap: true } },
      { type: 'category', gridIndex: 1, data: reactionHist.labels, name: '反应时间区间下限 (h)', axisLabel: { hideOverlap: true } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, name: '班次数' },
      { type: 'value', gridIndex: 1, name: '班次数' },
    ],
    series: [
      { name: '产率分布', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, data: yieldHist.counts, itemStyle: { color: '#167875' } },
      { name: '反应时间分布', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: reactionHist.counts, itemStyle: { color: '#bd7625' } },
    ],
  }
})

async function load() {
  if (!datasetId.value) return
  loading.value = true; error.value = ''
  try { data.value = await api.diagnostics(activeTab.value, scopeQuery.value) }
  catch (caught) { error.value = caught instanceof ApiError ? caught.message : '诊断数据加载失败' }
  finally { loading.value = false }
}

watch([scopeQuery, activeTab], () => void load(), { deep: true, immediate: true })
</script>

<template>
  <div class="view diagnostics-view">
    <PageHeader eyebrow="RULE-BASED DIAGNOSTICS" title="异常与故障" description="把规则、阈值和证据同时呈现，异常结论不冒充预测模型。">
      <div class="rule-chip"><span>R</span><div><strong>规则诊断</strong><small>非预测模型</small></div></div>
    </PageHeader>

    <div class="diagnostic-tabs" role="tablist" aria-label="诊断类型">
      <button v-for="tab in tabs" :key="tab.value" type="button" role="tab" :aria-selected="activeTab === tab.value" :class="{ active: activeTab === tab.value }" @click="activeTab = tab.value"><strong>{{ tab.label }}</strong><span>{{ tab.description }}</span></button>
    </div>
    <div v-if="loading" class="skeleton-stack"><el-skeleton :rows="12" animated /></div>
    <StatePanel v-else-if="!datasetId" title="请先选择数据版本" />
    <StatePanel v-else-if="error" tone="error" title="诊断数据加载失败" :description="error"><el-button type="primary" @click="load">重试</el-button></StatePanel>
    <template v-else-if="data">
      <section class="diagnostic-summary">
        <div><p>当前诊断</p><strong>{{ title }}</strong></div>
        <div><p>命中记录</p><strong>{{ data.rows.length.toLocaleString() }}</strong></div>
        <div v-if="activeTab === 'faults'"><p>严重告警</p><strong class="danger-text">{{ criticalCount }}</strong></div>
        <div><p>展示粒度</p><strong>{{ data.grain === 'shift' ? '班次记录' : '炉号 × 日期' }}</strong></div>
      </section>
      <EChart :title="`${title} · 可交互视图`" :filename="title" :option="chartOption" :height="activeTab === 'yield_heatmap' ? '680px' : '520px'">
        <el-table :data="data.rows" max-height="420" size="small">
          <el-table-column v-if="activeTab !== 'distribution'" prop="production_date" label="日期" width="110" />
          <el-table-column prop="production_line" label="产线" width="90" /><el-table-column prop="furnace" label="炉号" width="110" />
          <el-table-column v-if="activeTab === 'anomalies'" prop="rule" label="命中规则" min-width="210" /><el-table-column v-if="activeTab === 'anomalies'" prop="calculated_yield" label="产率" />
          <el-table-column v-if="activeTab === 'faults'" prop="level" label="等级" /><el-table-column v-if="activeTab === 'faults'" prop="fault_time" label="故障时长" />
          <el-table-column v-if="activeTab === 'yield_heatmap'" prop="weighted_yield" label="加权产率" />
          <el-table-column v-if="activeTab === 'distribution'" prop="reaction_time" label="反应时间" /><el-table-column v-if="activeTab === 'distribution'" prop="weighted_yield" label="产率" />
        </el-table>
      </EChart>
      <section v-if="activeTab === 'anomalies'" class="method-card"><span class="method-card__index">01</span><div><h2>规则如何工作</h2><p>对每个炉号分别计算产率均值与标准差，低于“均值 − 2σ”或配置的固定最低产率即标记。结果仅用于排查，不代表未来故障概率。</p></div><div><p>当前参数</p><strong>σ = {{ data.metadata.sigma }} · 最低产率 {{ data.metadata.minimum_yield ?? '未配置' }}</strong></div></section>
    </template>
  </div>
</template>
