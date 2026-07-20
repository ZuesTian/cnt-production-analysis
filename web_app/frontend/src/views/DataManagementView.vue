<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { api, ApiError } from '@/api/client'
import { useContextStore } from '@/stores/context'
import { useAuthStore } from '@/stores/auth'
import { useJobsStore } from '@/stores/jobs'
import type { DatasetSummary, JobStatus, QualityReport } from '@/types/api'
import PageHeader from '@/components/PageHeader.vue'
import QualityBadge from '@/components/QualityBadge.vue'
import StatePanel from '@/components/StatePanel.vue'
import { parseClipboardPreview, REQUIRED_SOURCE_HEADERS } from '@/utils/tabularPaste'

const context = useContextStore(); const jobs = useJobsStore(); const auth = useAuthStore()
const { datasets } = storeToRefs(context)
const { user } = storeToRefs(auth)
const kind = ref<'shared' | 'temporary'>('shared')
const sourceMode = ref<'file' | 'paste'>('file')
const name = ref('')
const file = ref<File | null>(null)
const pasteContent = ref('')
const job = ref<JobStatus | null>(null)
const quality = ref<QualityReport | null>(null)
const importing = ref(false)
const publishing = ref(false)
const deletingId = ref<string | null>(null)
const riskAcknowledged = ref(false)
const completeDates = ref<Record<string, string>>({})
const input = ref<HTMLInputElement>()
const acceptedExtensions = ['.xlsx', '.xlxs', '.xlsm', '.xls', '.ods', '.csv', '.tsv', '.txt']
const pastePreview = computed(() => parseClipboardPreview(pasteContent.value))
const sourceReady = computed(() => sourceMode.value === 'file' ? Boolean(file.value) : pastePreview.value.valid)

const step = computed(() => {
  if (!sourceReady.value) return 0
  if (job.value && ['queued', 'running'].includes(job.value.status)) return 1
  if (quality.value?.dataset.status === 'published') return 3
  if (quality.value) return 2
  return 0
})
const sharedDatasets = computed(() => datasets.value.filter((item) => item.kind === 'shared'))
const highIssues = computed(() => quality.value?.issues.filter((item) => ['high', 'critical'].includes(item.severity)) || [])
const canPublish = computed(() => quality.value?.dataset.kind === 'shared' && quality.value.dataset.status === 'ready' && (highIssues.value.length === 0 || riskAcknowledged.value))
const canDeleteDatasets = computed(() => user.value?.username === 'ztl')

function setSelectedFile(selected: File | null) {
  if (!selected) return
  const extension = selected.name.match(/\.[^.]+$/)?.[0].toLowerCase() || ''
  if (!acceptedExtensions.includes(extension)) { ElMessage.error(`不支持 ${extension || '无扩展名'} 文件，请选择 Excel、ODS 或分隔文本`); return }
  if (selected.size > 50 * 1024 * 1024) { ElMessage.error('文件超过 50MB 限制'); return }
  file.value = selected; name.value ||= selected.name.replace(/\.[^.]+$/, '')
  job.value = null; quality.value = null; riskAcknowledged.value = false
}

function fileSelected(event: Event) { setSelectedFile((event.target as HTMLInputElement).files?.[0] || null) }
function fileDropped(event: DragEvent) { setSelectedFile(event.dataTransfer?.files?.[0] || null) }

async function readClipboard() {
  try {
    pasteContent.value = await navigator.clipboard.readText()
    if (!pasteContent.value.trim()) ElMessage.warning('剪贴板中没有文本数据')
  } catch { ElMessage.warning('浏览器未授权读取剪贴板，请在输入框中按 Ctrl+V 粘贴') }
}

async function finishImport(accepted: { job_id: string; dataset_id: string }) {
  jobs.startPolling(); job.value = await jobs.waitFor(accepted.job_id)
  if (job.value.status !== 'completed') throw new Error(job.value.error_detail?.split('\n')[0] || '数据预检失败')
  quality.value = await api.quality(accepted.dataset_id)
  completeDates.value = { ...quality.value.dataset.complete_dates }
  await context.refreshDatasets()
  if (kind.value === 'temporary') {
    await context.selectDataset(accepted.dataset_id)
    ElMessage.success('临时数据预检完成，已切换为当前分析版本')
  } else ElMessage.success('共享快照预检完成，请确认质量报告后发布')
}

async function importSource() {
  if (!sourceReady.value) { ElMessage.warning(sourceMode.value === 'file' ? '请先选择数据文件' : pastePreview.value.error || '请先粘贴完整表格'); return }
  importing.value = true
  try {
    if (sourceMode.value === 'file' && file.value) {
      const form = new FormData(); form.append('file', file.value); form.append('kind', kind.value); form.append('name', name.value || file.value.name)
      await finishImport(await api.importDataset(form))
    } else {
      await finishImport(await api.importPastedDataset({ kind: kind.value, name: name.value || `粘贴数据 ${new Date().toLocaleDateString('zh-CN')}`, content: pasteContent.value }))
    }
  } catch (caught) {
    ElMessage.error(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : '导入失败')
  } finally { importing.value = false }
}

async function publish() {
  if (!quality.value || !canPublish.value) return
  try {
    await ElMessageBox.confirm(`发布后所有厂内访问者将看到“${quality.value.dataset.name}”，旧版本会自动归档。`, '确认发布共享数据', { confirmButtonText: '确认发布', cancelButtonText: '返回检查', type: 'warning' })
    publishing.value = true
    const result = await api.publish(quality.value.dataset.id, {
      confirm: true,
      complete_dates: completeDates.value,
      acknowledged_issue_codes: quality.value.issues.filter((item) => item.severity === 'high').map((item) => item.code),
    })
    quality.value.dataset = result
    await context.refreshDatasets(); await context.selectDataset(result.id)
    ElMessage.success('共享数据已发布')
  } catch (caught) {
    if (caught === 'cancel' || caught === 'close') return
    ElMessage.error(caught instanceof ApiError ? caught.message : '发布失败')
  } finally { publishing.value = false }
}

async function inspect(dataset: DatasetSummary) {
  quality.value = await api.quality(dataset.id); completeDates.value = { ...quality.value.dataset.complete_dates }; riskAcknowledged.value = false
  document.querySelector('.quality-preview')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function activate(dataset: DatasetSummary) {
  try {
    const report = await api.quality(dataset.id)
    await ElMessageBox.confirm(`将活动版本回滚到“${dataset.name}”？当前版本会保留为归档。`, '确认回滚数据版本', { confirmButtonText: '确认回滚', cancelButtonText: '取消', type: 'warning' })
    await api.publish(dataset.id, { confirm: true, complete_dates: dataset.complete_dates, acknowledged_issue_codes: report.issues.filter((item) => item.severity === 'high').map((item) => item.code) }, true)
    await context.refreshDatasets(); await context.selectDataset(dataset.id); ElMessage.success('活动数据版本已回滚')
  } catch (caught) { if (caught !== 'cancel' && caught !== 'close') ElMessage.error(caught instanceof ApiError ? caught.message : '回滚失败') }
}

async function removeDataset(dataset: DatasetSummary) {
  try {
    await ElMessageBox.confirm(`确认删除“${dataset.name}”？其源文件、分析记录和已生成报表将一并删除，且无法恢复。`, '确认删除数据版本', { confirmButtonText: '永久删除', cancelButtonText: '取消', type: 'error' })
    deletingId.value = dataset.id
    await api.deleteDataset(dataset.id)
    if (quality.value?.dataset.id === dataset.id) quality.value = null
    await context.refreshDatasets()
    ElMessage.success('数据版本已删除')
  } catch (caught) { if (caught !== 'cancel' && caught !== 'close') ElMessage.error(caught instanceof ApiError ? caught.message : '删除失败') } finally { deletingId.value = null }
}

function resetImport() {
  file.value = null; pasteContent.value = ''; name.value = ''; job.value = null; quality.value = null; riskAcknowledged.value = false
  if (input.value) input.value.value = ''
}
function severityLabel(value: string) { return ({ critical: '阻断', high: '高', medium: '中', low: '低', info: '信息' } as Record<string, string>)[value] || value }
onMounted(() => void context.refreshDatasets())
</script>

<template>
  <div class="view data-view">
    <div class="desktop-only-content">
      <PageHeader eyebrow="DATA GOVERNANCE" title="数据管理" description="每次共享导入都是不可变快照：预检、确认、发布，必要时可回滚。">
        <div class="data-policy"><span>7 种格式</span><span>100,000 行</span><span>24h 临时保留</span></div>
      </PageHeader>

      <section class="import-workbench">
        <header><div><p class="eyebrow">CONTROLLED IMPORT</p><h2>导入新数据版本</h2></div><el-steps :active="step" finish-status="success" simple><el-step title="提供数据" /><el-step title="自动预检" /><el-step title="质量确认" /><el-step title="发布" /></el-steps></header>
        <div class="import-grid">
          <div class="import-controls">
            <label class="control-label"><span>使用方式</span><el-segmented v-model="kind" :options="[{ label: '共享快照', value: 'shared' }, { label: '临时分析', value: 'temporary' }]" /></label>
            <label class="control-label"><span>版本名称</span><el-input v-model="name" maxlength="80" placeholder="例如：2026 年 4 月正式数据" /></label>
            <label class="control-label"><span>数据来源</span><el-segmented v-model="sourceMode" :options="[{ label: '上传文件', value: 'file' }, { label: '粘贴表格', value: 'paste' }]" /></label>
            <label v-if="sourceMode === 'file'" class="file-drop" @dragover.prevent @drop.prevent="fileDropped">
              <input ref="input" class="sr-only" type="file" accept=".xlsx,.xlxs,.xlsm,.xls,.ods,.csv,.tsv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" @change="fileSelected" />
              <span class="file-drop__symbol" aria-hidden="true">＋</span>
              <strong>{{ file ? file.name : '点击选择或拖入数据文件' }}</strong>
              <small>{{ file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : 'Excel：xlsx（兼容 xlxs）/ xlsm / xls · 表格：ods · 文本：csv / tsv / txt' }}</small>
            </label>
            <div v-else class="paste-source">
              <div class="paste-source__head"><div><strong>粘贴 Excel 单元格区域</strong><span>第一行应为字段名，支持制表符、逗号、分号或竖线</span></div><el-button plain @click="readClipboard">读取剪贴板</el-button></div>
              <el-input v-model="pasteContent" type="textarea" :rows="8" resize="vertical" aria-label="粘贴生产数据" :placeholder="`${REQUIRED_SOURCE_HEADERS.join('\t')}\n2026-07-01\t白班张三\tE01\t8\t0\t0\t800\t100`" />
              <div v-if="pasteContent" class="paste-status" :class="{ 'paste-status--error': !pastePreview.valid }">
                <span v-if="pastePreview.valid">已识别 {{ pastePreview.delimiterLabel }} · {{ pastePreview.columnCount }} 列 · 约 {{ pastePreview.totalRows.toLocaleString() }} 行</span>
                <span v-else>{{ pastePreview.error }}</span>
              </div>
              <div v-if="pastePreview.headers.length" class="paste-table-wrap" aria-label="粘贴数据预览">
                <table class="paste-table"><thead><tr><th v-for="(header, column) in pastePreview.headers" :key="`${header}-${column}`">{{ header }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in pastePreview.rows" :key="rowIndex"><td v-for="(_header, column) in pastePreview.headers" :key="column">{{ row[column] || '' }}</td></tr></tbody></table>
              </div>
            </div>
            <div class="import-actions"><el-button @click="resetImport">清空</el-button><el-button type="primary" :loading="importing" :disabled="!sourceReady" @click="importSource">{{ sourceMode === 'file' ? '上传并预检' : '粘贴并预检' }}</el-button></div>
          </div>
          <aside class="import-explainer">
            <div><span>01</span><p><strong>格式与表头识别</strong>校验真实格式，并自动查找前 30 行中的字段表头</p></div>
            <div><span>02</span><p><strong>可信度分析</strong>配对完整率、空记录、重复粒度、班组变体</p></div>
            <div><span>03</span><p><strong>不可变入库</strong>建立版本、炉日聚合建议与文件哈希</p></div>
          </aside>
        </div>
        <div v-if="job && ['queued','running'].includes(job.status)" class="import-progress" role="status"><div><strong>{{ job.message }}</strong><span>{{ job.phase }}</span></div><el-progress :percentage="job.progress" /></div>
      </section>

      <section v-if="quality" class="quality-preview">
        <header><div><p class="eyebrow">QUALITY GATE</p><h2>预检结果</h2><p>{{ quality.dataset.row_count.toLocaleString() }} 条班次记录 · {{ quality.dataset.furnace_count }} 个炉号 · {{ quality.dataset.date_min }} 至 {{ quality.dataset.date_max }}</p></div><QualityBadge :status="quality.dataset.quality_status" /></header>
        <div class="quality-stats"><div><span>有效生产班次</span><strong>{{ quality.dataset.valid_production_count.toLocaleString() }}</strong></div><div><span>质量问题类型</span><strong>{{ quality.issues.length }}</strong></div><div><span>高等级风险</span><strong>{{ highIssues.length }}</strong></div><div><span>活动状态</span><strong>{{ quality.dataset.status }}</strong></div></div>
        <div class="complete-date-grid">
          <label v-for="(coverage, line) in quality.dataset.coverage" :key="line"><span>{{ line }} 最新完整日 <em v-if="!coverage.suggested_verified">需人工确认</em></span><el-date-picker v-model="completeDates[line]" value-format="YYYY-MM-DD" type="date" /><small>源数据最新 {{ coverage.date_max }}，覆盖率 {{ (coverage.latest_coverage_ratio * 100).toFixed(0) }}%</small></label>
        </div>
        <div class="issue-list">
          <article v-for="issue in quality.issues" :key="issue.code"><span :class="`severity severity--${issue.severity}`">{{ severityLabel(issue.severity) }}</span><div><strong>{{ issue.title }}</strong><p>{{ issue.description }}</p><code>{{ issue.code }}</code></div><b>{{ issue.affected_count.toLocaleString() }}<small>{{ (issue.affected_rate * 100).toFixed(1) }}%</small></b></article>
        </div>
        <footer v-if="quality.dataset.kind === 'shared' && quality.dataset.status === 'ready'">
          <el-checkbox v-model="riskAcknowledged" size="large">我已核对完整日，并理解高等级质量风险将随版本一同发布</el-checkbox>
          <el-button type="primary" :loading="publishing" :disabled="!canPublish" @click="publish">二次确认并发布</el-button>
        </footer>
        <footer v-else-if="quality.dataset.kind === 'temporary'"><span>临时版本仅当前浏览器可见，将在 24 小时后自动清理。</span><RouterLink class="primary-link" to="/">进入生产总览</RouterLink></footer>
      </section>

      <section class="versions-panel">
        <header><div><p class="eyebrow">VERSION HISTORY</p><h2>共享数据版本</h2></div><span>发布与回滚均记录时间、客户端地址和文件哈希</span></header>
        <el-table :data="sharedDatasets" empty-text="尚无共享数据版本">
          <el-table-column label="版本" min-width="260"><template #default="scope"><div class="version-name"><strong>{{ scope.row.name }}</strong><span>{{ scope.row.original_filename }}</span></div></template></el-table-column>
          <el-table-column label="状态" width="120"><template #default="scope"><span class="version-status" :class="`version-status--${scope.row.status}`">{{ scope.row.status }}</span></template></el-table-column>
          <el-table-column label="质量" width="130"><template #default="scope"><QualityBadge :status="scope.row.quality_status" compact /></template></el-table-column>
          <el-table-column prop="row_count" label="班次记录" width="120" /><el-table-column prop="date_max" label="数据截止" width="120" /><el-table-column prop="created_at" label="导入时间" width="190" />
          <el-table-column label="操作" width="250"><template #default="scope"><el-button link type="primary" @click="inspect(scope.row)">质量报告</el-button><el-button v-if="scope.row.status === 'archived'" link type="warning" @click="activate(scope.row)">回滚至此</el-button><el-button v-if="canDeleteDatasets && scope.row.status !== 'published'" link type="danger" :loading="deletingId === scope.row.id" @click="removeDataset(scope.row)">删除</el-button></template></el-table-column>
        </el-table>
      </section>
    </div>
    <div class="mobile-only-content"><StatePanel tone="info" title="数据发布需要桌面或平板" description="手机端不开放共享发布和复杂质量确认，避免误操作。"><RouterLink class="primary-link" to="/">返回总览</RouterLink></StatePanel></div>
  </div>
</template>
