<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { api, ApiError } from '@/api/client'
import { useContextStore } from '@/stores/context'
import type { OverviewResponse, SeriesResponse } from '@/types/api'
import EChart from '@/components/EChart.vue'
import PageHeader from '@/components/PageHeader.vue'
import QualityBadge from '@/components/QualityBadge.vue'
import StatePanel from '@/components/StatePanel.vue'
import { formatMetric } from '@/utils/metrics'

const context = useContextStore()
const { datasetId, scopeQuery, activeDataset } = storeToRefs(context)
const overview = ref<OverviewResponse | null>(null)
const trend = ref<SeriesResponse | null>(null)
const ranking = ref<SeriesResponse | null>(null)
const loading = ref(false)
const error = ref('')

function trendCategory(row: Record<string, unknown>) {
  const date = String(row.production_date)
  return row.shift_name ? `${date} · ${String(row.shift_name)}` : date
}

const trendOption = computed(() => {
  const rows = trend.value?.rows || []
  const categories = [...new Set(rows.map(trendCategory))]
  const lines = [...new Set(rows.map((row) => String(row.production_line)))]
  const series = lines.flatMap((line) => {
    const byCategory = new Map(rows.filter((row) => row.production_line === line).map((row) => [trendCategory(row), row]))
    return [
      { name: `${line} 产量`, type: 'bar', stack: 'output', data: categories.map((category) => byCategory.get(category)?.total_output ?? null), itemStyle: { color: line.includes('L3') ? '#167875' : '#76a9a2' }, emphasis: { focus: 'series' } },
      { name: `${line} 加权产率`, type: 'line', yAxisIndex: 1, smooth: 0.25, symbol: 'circle', symbolSize: 5, data: categories.map((category) => byCategory.get(category)?.weighted_yield ?? null), lineStyle: { width: 2, type: line.includes('L3') ? 'solid' : 'dashed' }, itemStyle: { color: line.includes('L3') ? '#bd7625' : '#8c5936' } },
    ]
  })
  return {
    color: ['#167875', '#bd7625', '#76a9a2', '#8c5936'],
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : String(value ?? '—') },
    legend: { top: 0, left: 0, textStyle: { color: '#54615f' } },
    grid: { left: 62, right: 64, top: 48, bottom: 52 },
    xAxis: { type: 'category', data: categories, axisLabel: { formatter: (value: string) => value.slice(5).replace(' · ', ' '), hideOverlap: true }, axisLine: { lineStyle: { color: '#cfd5d1' } } },
    yAxis: [
      { type: 'value', name: '产量 kg', splitLine: { lineStyle: { color: '#e8e9e5' } } },
      { type: 'value', name: '产率 kg/h', splitLine: { show: false } },
    ],
    dataZoom: categories.length > 45 ? [{ type: 'inside', start: 55, end: 100 }, { type: 'slider', height: 18, bottom: 6 }] : [],
    series,
  }
})

const rankingOption = computed(() => {
  const rows = [...(ranking.value?.rows || [])].slice(0, 12).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 90, right: 36, top: 12, bottom: 32 },
    xAxis: { type: 'value', name: 'kg/h', splitLine: { lineStyle: { color: '#e8e9e5' } } },
    yAxis: { type: 'category', data: rows.map((row) => String(row.furnace)), axisTick: { show: false } },
    series: [{ type: 'bar', name: '加权产率', data: rows.map((row) => row.weighted_yield), barWidth: 14, itemStyle: { color: '#167875', borderRadius: [0, 4, 4, 0] } }],
  }
})

async function load() {
  if (!datasetId.value) return
  loading.value = true
  error.value = ''
  try {
    const [overviewData, trendData, rankingData] = await Promise.all([
      api.overview(scopeQuery.value),
      api.trends(scopeQuery.value),
      api.ranking({ ...scopeQuery.value, metric: 'weighted_yield', limit: '20' }),
    ])
    overview.value = overviewData
    trend.value = trendData
    ranking.value = rankingData
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '数据加载失败，请稍后重试'
  } finally { loading.value = false }
}

watch(scopeQuery, () => void load(), { deep: true, immediate: true })
</script>

<template>
  <div class="view dashboard-view">
    <PageHeader eyebrow="OPERATIONS OVERVIEW" title="生产总览" description="以每条产线的最新完整日为基准，先看结果，再追踪驱动与可信度。">
      <div v-if="overview" class="header-meta">
        <QualityBadge :status="overview.dataset.quality_status" />
        <span>共同对比日 <strong>{{ overview.common_comparison_date || '暂无' }}</strong></span>
      </div>
    </PageHeader>

    <div v-if="loading" class="skeleton-stack" aria-label="正在加载生产总览">
      <el-skeleton :rows="2" animated /><div class="skeleton-grid"><el-skeleton v-for="i in 6" :key="i" :rows="2" animated /></div><el-skeleton :rows="8" animated />
    </div>
    <StatePanel v-else-if="!datasetId" title="还没有可分析的数据" description="请在数据管理中导入共享快照或临时分析文件。">
      <RouterLink class="primary-link" to="/data">前往数据管理</RouterLink>
    </StatePanel>
    <StatePanel v-else-if="error" tone="error" title="总览暂时无法加载" :description="error"><el-button type="primary" @click="load">重新加载</el-button></StatePanel>

    <template v-else-if="overview">
      <section class="trust-strip" aria-label="数据可信度护栏">
        <div><span class="trust-strip__mark">截止</span><p>数据版本</p><strong>{{ activeDataset?.date_min }} — {{ activeDataset?.date_max }}</strong></div>
        <div><span class="trust-strip__mark trust-strip__mark--good">配对</span><p>有效生产班次</p><strong>{{ activeDataset?.valid_production_count.toLocaleString() }} / {{ activeDataset?.row_count.toLocaleString() }}</strong></div>
        <div><span class="trust-strip__mark trust-strip__mark--warn">风险</span><p>高等级问题</p><strong>{{ (overview.quality_issue_counts.high || 0) + (overview.quality_issue_counts.critical || 0) }} 项</strong></div>
        <p class="trust-strip__note">产率仅使用产量与反应时间均有效的班次记录</p>
      </section>

      <section v-for="snapshot in overview.line_snapshots" :key="snapshot.production_line" class="line-snapshot">
        <header class="line-snapshot__head">
          <div><span class="line-code">{{ snapshot.production_line }}</span><div><h2>{{ snapshot.production_line }} 产线</h2><p>{{ snapshot.snapshot_date }} · {{ snapshot.is_confirmed_complete ? '已确认完整日' : '建议完整日待确认' }}</p></div></div>
          <div class="line-diagnostics"><span><b>{{ snapshot.active_furnaces }}</b> 运行炉</span><span :class="{ danger: snapshot.serious_alerts > 0 }"><b>{{ snapshot.serious_alerts }}</b> 严重预警</span><span><b>{{ (snapshot.pairing_completeness * 100).toFixed(1) }}%</b> 配对完整</span></div>
        </header>
        <div class="kpi-grid">
          <article v-for="kpi in snapshot.kpis" :key="kpi.key" class="kpi-card" :class="`kpi-card--${kpi.key}`">
            <p>{{ kpi.label }}</p><strong>{{ formatMetric(kpi.value, kpi.unit) }}</strong>
            <span v-if="kpi.delta_percent !== null" :class="{ down: kpi.delta_percent < 0, risk: kpi.key === 'fault_hours' && kpi.delta_percent > 0 }">
              {{ kpi.delta_percent > 0 ? '↑' : '↓' }} {{ Math.abs(kpi.delta_percent).toFixed(1) }}% <small>较前一日</small>
            </span>
            <span v-else class="muted">暂无可比前日</span>
          </article>
        </div>
      </section>

      <div class="analytics-grid">
        <EChart class="analytics-grid__wide" title="日产量与加权产率趋势" filename="生产趋势" :option="trendOption" height="390px">
          <el-table :data="trend?.rows || []" max-height="320" size="small"><el-table-column prop="production_date" label="日期" /><el-table-column v-if="trend?.grain === 'shift'" prop="shift_name" label="班次" /><el-table-column prop="production_line" label="产线" /><el-table-column prop="total_output" label="总产量" /><el-table-column prop="weighted_yield" label="加权产率" /><el-table-column prop="fault_hours" label="故障时长" /></el-table>
        </EChart>
        <EChart title="炉号产率排名" filename="炉号产率排名" :option="rankingOption" height="390px">
          <el-table :data="ranking?.rows || []" max-height="320" size="small"><el-table-column prop="furnace" label="炉号" /><el-table-column prop="production_line" label="产线" /><el-table-column prop="weighted_yield" label="加权产率" /></el-table>
        </EChart>
      </div>

      <section class="risk-panel">
        <header><div><p class="eyebrow">DATA TRUST</p><h2>需要关注的数据风险</h2></div><RouterLink to="/data">查看完整质量报告 →</RouterLink></header>
        <div v-if="overview.top_risks.length" class="risk-list">
          <article v-for="risk in overview.top_risks" :key="risk.code"><span :class="`risk-level risk-level--${risk.severity}`">{{ risk.severity }}</span><div><strong>{{ risk.title }}</strong><p>{{ risk.description }}</p></div><b>{{ risk.affected_count.toLocaleString() }} 条</b></article>
        </div>
        <p v-else class="muted">当前版本未发现数据质量风险。</p>
      </section>
    </template>
  </div>
</template>
