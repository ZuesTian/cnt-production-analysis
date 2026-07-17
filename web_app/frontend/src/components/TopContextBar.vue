<script setup lang="ts">
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useContextStore } from '@/stores/context'
import QualityBadge from './QualityBadge.vue'

const emit = defineEmits<{ change: [] }>()
const context = useContextStore()
const {
  datasets, datasetId, grain, productionLines, furnaces, dateRange,
  filters, activeDataset, availableFurnaces,
} = storeToRefs(context)
const mobileOpen = ref(false)

async function datasetChanged(value: string) {
  await context.selectDataset(value)
  emit('change')
}

function changed() { emit('change') }
function reset() { context.resetScope(); emit('change') }
</script>

<template>
  <header class="context-header">
    <div class="context-header__summary">
      <button class="mobile-filter-button" type="button" aria-label="打开全局筛选" @click="mobileOpen = true">
        <span aria-hidden="true">⌁</span> 筛选
      </button>
      <div v-if="activeDataset" class="dataset-context">
        <span class="dataset-kind" :class="`dataset-kind--${activeDataset.kind}`">{{ activeDataset.kind === 'shared' ? '共享' : '临时' }}</span>
        <div><strong>{{ activeDataset.name }}</strong><span>截止 {{ Object.values(activeDataset.complete_dates).sort().at(-1) || activeDataset.date_max || '—' }}</span></div>
        <QualityBadge :status="activeDataset.quality_status" compact />
      </div>
      <div v-else class="dataset-context dataset-context--empty"><span>尚未选择数据版本</span></div>
      <slot name="mobile-title" />
    </div>

    <div class="filter-row desktop-filters" aria-label="全局数据筛选">
      <label class="field field--dataset"><span>数据版本</span>
        <el-select :model-value="datasetId" placeholder="选择数据" @change="datasetChanged">
          <el-option v-for="item in datasets" :key="item.id" :label="`${item.kind === 'shared' ? '共享' : '临时'} · ${item.name}`" :value="item.id" />
        </el-select>
      </label>
      <label class="field"><span>产线</span>
        <el-select v-model="productionLines" multiple collapse-tags clearable placeholder="全部产线" @change="changed">
          <el-option v-for="line in filters?.production_lines || []" :key="line" :label="line" :value="line" />
        </el-select>
      </label>
      <label class="field field--furnace"><span>炉号</span>
        <el-select v-model="furnaces" multiple filterable collapse-tags clearable placeholder="全部炉号" @change="changed">
          <el-option v-for="item in availableFurnaces" :key="item" :label="item" :value="item" />
        </el-select>
      </label>
      <label class="field field--date"><span>日期范围</span>
        <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" clearable @change="changed" />
      </label>
      <label class="field field--grain"><span>分析粒度</span>
        <el-segmented v-model="grain" :options="[{ label: '炉日', value: 'furnace_day' }, { label: '班次', value: 'shift' }]" @change="changed" />
      </label>
      <button class="reset-button" type="button" @click="reset">重置</button>
    </div>
  </header>

  <el-drawer v-model="mobileOpen" title="筛选当前视图" direction="btt" size="78%" class="mobile-filter-drawer">
    <div class="mobile-filter-form">
      <label class="field"><span>数据版本</span><el-select :model-value="datasetId" @change="datasetChanged"><el-option v-for="item in datasets" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
      <label class="field"><span>产线</span><el-select v-model="productionLines" multiple clearable @change="changed"><el-option v-for="line in filters?.production_lines || []" :key="line" :label="line" :value="line" /></el-select></label>
      <label class="field"><span>炉号</span><el-select v-model="furnaces" filterable clearable @change="changed"><el-option v-for="item in availableFurnaces" :key="item" :label="item" :value="item" /></el-select></label>
      <label class="field"><span>日期范围</span><el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" @change="changed" /></label>
      <div class="mobile-filter-actions"><el-button @click="reset">重置</el-button><el-button type="primary" @click="mobileOpen = false">查看结果</el-button></div>
    </div>
  </el-drawer>
</template>
