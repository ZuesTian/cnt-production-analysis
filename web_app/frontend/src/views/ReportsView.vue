<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { api, ApiError } from '@/api/client'
import { useContextStore } from '@/stores/context'
import { useJobsStore } from '@/stores/jobs'
import type { ExportArtifact } from '@/types/api'
import PageHeader from '@/components/PageHeader.vue'
import StatePanel from '@/components/StatePanel.vue'

const context = useContextStore(); const jobs = useJobsStore()
const { datasetId, productionLines, furnaces, dateRange } = storeToRefs(context)
const exports = ref<ExportArtifact[]>([]); const creating = ref('')
const reportTypes = [
  { value: 'daily_summary', title: '每日生产汇总', description: '产量、加权产率、反应与停机时长', accent: 'teal' },
  { value: 'monthly_summary', title: '月度经营汇总', description: '按月及产线的趋势和对比', accent: 'green' },
  { value: 'furnace_stats', title: '炉号统计', description: '炉号明细、月均与前后排名', accent: 'amber' },
  { value: 'furnace_daily_trend', title: '单炉每日数据', description: '供追溯和二次分析的明细工作簿', accent: 'blue' },
  { value: 'anomaly', title: '规则异常报告', description: '固定阈值与炉号内 2σ 命中记录', accent: 'orange' },
  { value: 'fault_warning', title: '故障预警报告', description: '单日、连续与月累计故障告警', accent: 'red' },
]

async function refresh() { exports.value = await api.exports(); await jobs.refresh() }
async function create(reportType: string) {
  if (!datasetId.value) return
  creating.value = reportType
  try {
    const result = await api.createExport({ dataset_id: datasetId.value, report_type: reportType, production_lines: productionLines.value, furnaces: furnaces.value, date_from: dateRange.value[0], date_to: dateRange.value[1] })
    jobs.startPolling(); ElMessage.success('报表作业已提交，可继续浏览其他页面')
    const completed = await jobs.waitFor(result.job_id)
    if (completed.status === 'completed') { ElMessage.success('报表已生成'); await refresh() }
    else throw new Error(completed.error_detail || '报表生成失败')
  } catch (caught) { ElMessage.error(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : '报表生成失败') }
  finally { creating.value = '' }
}
function formatBytes(value: number) { return value > 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(value / 1024)} KB` }
onMounted(() => void refresh())
</script>

<template>
  <div class="view reports-view">
    <div class="desktop-only-content">
      <PageHeader eyebrow="REPORT CENTER" title="报表中心" description="报表在后台生成，页面无需等待；全部文件保存在当前数据版本下。">
        <el-button type="primary" :loading="creating === 'all'" @click="create('all')">生成完整报表包</el-button>
      </PageHeader>
      <StatePanel v-if="!datasetId" title="请先选择数据版本" />
      <template v-else>
        <section class="report-card-grid">
          <article v-for="report in reportTypes" :key="report.value" class="report-card" :class="`report-card--${report.accent}`"><span class="report-card__mark" /><div><p>EXCEL REPORT</p><h2>{{ report.title }}</h2><span>{{ report.description }}</span></div><el-button :loading="creating === report.value" @click="create(report.value)">生成报表</el-button></article>
        </section>
        <section class="exports-panel"><header><div><p class="eyebrow">DELIVERY HISTORY</p><h2>已生成文件</h2></div><el-button @click="refresh">刷新</el-button></header>
          <el-table :data="exports" empty-text="尚未生成报表">
            <el-table-column prop="filename" label="文件" min-width="300" /><el-table-column prop="report_type" label="类型" width="160" /><el-table-column label="大小" width="110"><template #default="scope">{{ formatBytes(scope.row.size) }}</template></el-table-column><el-table-column prop="created_at" label="生成时间" width="190" /><el-table-column label="操作" width="110"><template #default="scope"><a class="table-link" :href="`/api/v1/exports/${scope.row.id}/download`">下载</a></template></el-table-column>
          </el-table>
        </section>
      </template>
    </div>
    <div class="mobile-only-content"><StatePanel tone="info" title="请在桌面或平板生成报表" description="手机端保留总览、告警和炉号查询，复杂报表操作需要更大的工作区。"><RouterLink class="primary-link" to="/">返回总览</RouterLink></StatePanel></div>
  </div>
</template>
