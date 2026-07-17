<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; compact?: boolean }>()
const config = computed(() => ({
  pass: { label: '质量通过', tone: 'ok' },
  warning: { label: '存在风险', tone: 'warn' },
  blocked: { label: '发布阻断', tone: 'danger' },
  pending: { label: '预检中', tone: 'neutral' },
}[props.status] || { label: props.status, tone: 'neutral' }))
</script>

<template>
  <span class="quality-badge" :class="`quality-badge--${config.tone}`">
    <span class="quality-badge__mark" aria-hidden="true" />
    <span>{{ compact ? config.label.replace('质量', '') : config.label }}</span>
  </span>
</template>
