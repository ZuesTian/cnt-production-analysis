<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, ApiError } from '@/api/client'

const accessKey = ref('')
const checking = ref(false)
const ready = ref(!api.requiresAccessKey || api.hasAccessToken())

function requireAuthentication() {
  if (!api.requiresAccessKey) return
  api.clearAccessToken()
  accessKey.value = ''
  ready.value = false
}

async function connect() {
  if (!accessKey.value.trim()) return
  checking.value = true
  api.setAccessToken(accessKey.value)
  try {
    await api.verifyAccess()
    ready.value = true
    accessKey.value = ''
  } catch (caught) {
    api.clearAccessToken()
    ElMessage.error(caught instanceof ApiError ? caught.message : '无法连接生产数据服务')
  } finally {
    checking.value = false
  }
}

onMounted(() => window.addEventListener('cnt-auth-required', requireAuthentication))
onBeforeUnmount(() => window.removeEventListener('cnt-auth-required', requireAuthentication))
</script>

<template>
  <RouterView v-if="ready" />
  <main v-else class="auth-gate">
    <div class="auth-gate__brand"><span aria-hidden="true" />CNT Production Workbench</div>
    <section aria-labelledby="auth-title">
      <p>SECURE API</p>
      <h1 id="auth-title">连接生产数据服务</h1>
      <label for="access-key">访问密钥</label>
      <el-input id="access-key" v-model="accessKey" type="password" show-password size="large" autocomplete="current-password" @keyup.enter="connect" />
      <el-button type="primary" size="large" :loading="checking" :disabled="!accessKey.trim()" @click="connect">连接</el-button>
      <small>密钥仅保存在此浏览器中，不会写入 GitHub Pages。</small>
    </section>
  </main>
</template>

<style scoped>
.auth-gate{min-height:100vh;padding:28px clamp(20px,5vw,72px);background:#f3f1ec;color:#173332}.auth-gate__brand{display:flex;align-items:center;gap:12px;font-weight:800}.auth-gate__brand span{width:30px;height:30px;border-radius:6px;background:#167875}.auth-gate section{width:min(440px,100%);margin:18vh auto 0}.auth-gate p{margin:0 0 10px;color:#167875;font-size:12px;font-weight:800;letter-spacing:0}.auth-gate h1{margin:0 0 30px;font-size:34px;letter-spacing:0}.auth-gate label{display:block;margin-bottom:8px;font-weight:700}.auth-gate .el-button{width:100%;margin-top:14px}.auth-gate small{display:block;margin-top:16px;color:#667573;line-height:1.6}
</style>
