<script setup lang="ts">
withDefaults(defineProps<{ title: string; description?: string; tone?: 'empty' | 'error' | 'info' }>(), { tone: 'empty' })
</script>

<template>
  <section class="state-panel" :class="`state-panel--${tone}`" role="status">
    <div class="state-panel__symbol" aria-hidden="true">{{ tone === 'error' ? '!' : tone === 'info' ? 'i' : '○' }}</div>
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
    <div class="state-panel__actions"><slot /></div>
  </section>
</template>
