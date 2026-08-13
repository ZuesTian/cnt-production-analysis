<script setup lang="ts">
import { computed } from 'vue'
import { activeTheme, toggleTheme } from '@/theme'

const nextLabel = computed(() => activeTheme.value === 'dark' ? '浅色' : '深色')
</script>

<template>
  <button
    class="theme-toggle"
    data-theme-toggle
    type="button"
    :aria-label="`切换到${nextLabel}模式`"
    :title="`切换到${nextLabel}模式`"
    :aria-pressed="activeTheme === 'dark'"
    @click="toggleTheme"
  >
    <span aria-hidden="true">{{ activeTheme === 'dark' ? '☀' : '☾' }}</span>
    <small>{{ nextLabel }}</small>
  </button>
</template>

<style scoped>
.theme-toggle{display:inline-flex;min-width:76px;min-height:38px;align-items:center;justify-content:center;gap:7px;padding:0 10px;border:1px solid var(--border);border-radius:9px;color:var(--muted);background:var(--surface);cursor:pointer;font-weight:750;transition:.2s ease}
.theme-toggle:hover{color:var(--teal);border-color:color-mix(in srgb,var(--teal) 42%,var(--border));transform:translateY(-1px)}
.theme-toggle>span{width:16px;font-size:14px}.theme-toggle small{font-size:10px}
@media(max-width:767px){.theme-toggle{min-width:42px;width:42px;padding:0}.theme-toggle small{display:none}}
</style>
