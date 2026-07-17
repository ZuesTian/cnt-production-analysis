<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { use, init, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { BarChart, BoxplotChart, HeatmapChart, LineChart } from 'echarts/charts'
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

use([
  BarChart, BoxplotChart, HeatmapChart, LineChart, AriaComponent, DataZoomComponent,
  GridComponent, LegendComponent, MarkLineComponent, TitleComponent, ToolboxComponent,
  TooltipComponent, VisualMapComponent, SVGRenderer,
])

const props = withDefaults(defineProps<{
  option: EChartsCoreOption
  height?: string
  title?: string
  filename?: string
}>(), { height: '360px', title: '数据图表', filename: 'chart' })

const chartEl = ref<HTMLDivElement>()
let chart: ECharts | null = null
let observer: ResizeObserver | null = null

function render() {
  if (!chartEl.value) return
  if (!chart) chart = init(chartEl.value, undefined, { renderer: 'svg' })
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  chart.setOption({ animation: !reduceMotion, aria: { enabled: true, decal: { show: true } }, ...props.option }, { notMerge: true })
}

function saveDataUrl(url: string, extension: string) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${props.filename}.${extension}`
  anchor.click()
}

function currentSvg(): string | null {
  return chart?.getDom().querySelector('svg')?.outerHTML || null
}

function exportPng() {
  const svg = currentSvg()
  if (!svg || !chartEl.value) return
  const blobUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }))
  const image = new Image()
  image.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = chartEl.value!.clientWidth * 2
    canvas.height = chartEl.value!.clientHeight * 2
    const context = canvas.getContext('2d')
    if (context) {
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      saveDataUrl(canvas.toDataURL('image/png'), 'png')
    }
    URL.revokeObjectURL(blobUrl)
  }
  image.src = blobUrl
}

function exportSvg() {
  const svg = currentSvg()
  if (svg) saveDataUrl(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, 'svg')
}

watch(() => props.option, () => void nextTick(render), { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  if (chartEl.value) observer.observe(chartEl.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <section class="chart-frame">
    <div class="chart-frame__toolbar">
      <h3>{{ title }}</h3>
      <div class="chart-actions" aria-label="图表导出">
        <button type="button" @click="exportPng">PNG</button>
        <button type="button" @click="exportSvg">SVG</button>
      </div>
    </div>
    <div ref="chartEl" class="chart-canvas" :style="{ height }" role="img" :aria-label="title" />
    <details class="chart-details"><summary>查看图表明细表</summary><slot /></details>
  </section>
</template>
