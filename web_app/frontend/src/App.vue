<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { RouterView } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import ThemeToggle from '@/components/ThemeToggle.vue'

const auth = useAuthStore()
const { ready, checking } = storeToRefs(auth)
const username = ref('')
const password = ref('')

function requireAuthentication() {
  auth.requireAuthentication()
  password.value = ''
}

async function signIn() {
  if (!username.value.trim() || !password.value) return
  try {
    await auth.login(username.value, password.value)
    password.value = ''
  } catch (caught) {
    ElMessage.error(caught instanceof ApiError ? caught.message : '暂时无法登录，请稍后重试')
  }
}

onMounted(() => {
  window.addEventListener('cnt-auth-required', requireAuthentication)
  void auth.initialize()
})
onBeforeUnmount(() => window.removeEventListener('cnt-auth-required', requireAuthentication))
</script>

<template>
  <RouterView v-if="ready" />
  <main v-else class="login-page">
    <div class="login-page__top">
      <div class="login-page__brand">
        <span class="login-page__mark" aria-hidden="true"><i /><i /><i /></span>
        <span><strong>生产分析台</strong><small>CNT PRODUCTION WORKBENCH</small></span>
      </div>
      <ThemeToggle />
    </div>
    <div class="login-page__grid">
      <section class="login-intro" aria-label="系统说明">
        <p>PRODUCTION INTELLIGENCE</p>
        <h1>让每一炉生产数据<br>成为可执行的判断。</h1>
        <div class="login-intro__rule" />
        <p class="login-intro__copy">统一查看产量、收率、异常、炉号表现与质量门禁，只向已授权成员开放。</p>
        <dl>
          <div><dt>双粒度</dt><dd>炉日与班次</dd></div>
          <div><dt>可追溯</dt><dd>版本与报表</dd></div>
          <div><dt>受保护</dt><dd>账号会话认证</dd></div>
        </dl>
      </section>
      <section class="login-card" aria-labelledby="login-title">
        <p class="login-card__eyebrow">MEMBER ACCESS</p>
        <h2 id="login-title">登录生产分析台</h2>
        <p class="login-card__hint">请输入分配给你的账号和密码</p>
        <form @submit.prevent="signIn">
          <label for="username">账号</label>
          <el-input id="username" v-model="username" size="large" autocomplete="username" maxlength="32" autofocus placeholder="请输入账号" />
          <label for="password">密码</label>
          <el-input id="password" v-model="password" type="password" show-password size="large" autocomplete="current-password" maxlength="128" placeholder="请输入密码" />
          <el-button native-type="submit" type="primary" size="large" :loading="checking" :disabled="!username.trim() || !password">登录</el-button>
        </form>
        <small>登录状态仅保存在当前浏览器；退出后将清除。</small>
      </section>
    </div>
    <footer>AUTHORIZED INTERNAL USE · CNT ANALYTICS</footer>
  </main>
</template>

<style scoped>
.login-page{display:flex;min-height:100vh;flex-direction:column;padding:32px clamp(24px,5vw,80px) 24px;overflow:hidden;color:var(--ink);background:linear-gradient(135deg,var(--canvas) 0%,color-mix(in srgb,var(--surface) 52%,var(--canvas)) 52%,color-mix(in srgb,var(--teal-soft) 62%,var(--canvas)) 100%)}
.login-page::before{position:fixed;width:560px;height:560px;border:1px solid rgba(22,120,117,.14);border-radius:50%;content:"";right:-210px;top:-250px;box-shadow:0 0 0 70px rgba(22,120,117,.035),0 0 0 150px rgba(22,120,117,.025)}
.login-page__top{position:relative;display:flex;align-items:center;justify-content:space-between;gap:20px}
.login-page__brand{position:relative;display:flex;align-items:center;gap:12px}.login-page__brand>span:last-child{display:flex;flex-direction:column}.login-page__brand strong{font-size:15px;letter-spacing:.08em}.login-page__brand small{margin-top:2px;color:var(--quiet);font-size:8px;letter-spacing:.18em}.login-page__mark{display:flex;width:38px;height:38px;align-items:flex-end;justify-content:center;gap:3px;padding:8px;border-radius:9px;background:var(--teal);box-shadow:0 8px 22px color-mix(in srgb,var(--teal) 20%,transparent)}.login-page__mark i{display:block;width:4px;border-radius:2px;background:#d9eee5}.login-page__mark i:nth-child(1){height:11px}.login-page__mark i:nth-child(2){height:20px}.login-page__mark i:nth-child(3){height:15px}
.login-page__grid{position:relative;display:grid;width:min(1120px,100%);grid-template-columns:minmax(0,1.2fr) minmax(340px,440px);align-items:center;gap:clamp(48px,8vw,120px);margin:auto}.login-intro>p:first-child,.login-card__eyebrow{margin:0;color:var(--teal);font-size:11px;font-weight:800;letter-spacing:.2em}.login-intro h1{margin:18px 0 28px;font-family:Georgia,"Noto Serif SC",serif;font-size:clamp(38px,4.3vw,64px);font-weight:500;line-height:1.18;letter-spacing:-.035em}.login-intro__rule{width:76px;height:3px;background:var(--amber)}.login-intro__copy{max-width:520px;margin:24px 0 34px;color:var(--muted);font-size:15px;line-height:1.9}.login-intro dl{display:grid;max-width:520px;grid-template-columns:repeat(3,1fr);margin:0}.login-intro dl div{padding:0 18px;border-left:1px solid var(--border)}.login-intro dl div:first-child{padding-left:0;border:0}.login-intro dt{font-size:14px;font-weight:800}.login-intro dd{margin:5px 0 0;color:var(--quiet);font-size:11px}
.login-card{padding:42px 40px 36px;border:1px solid var(--border);border-radius:18px;background:color-mix(in srgb,var(--surface) 88%,transparent);box-shadow:var(--shadow-md);backdrop-filter:blur(18px)}.login-card h2{margin:10px 0 8px;font-size:28px;letter-spacing:-.04em}.login-card__hint{margin:0 0 30px;color:var(--muted);font-size:13px}.login-card form{display:grid;gap:8px}.login-card label{margin-top:9px;color:var(--ink);font-size:12px;font-weight:750}.login-card :deep(.el-input__wrapper){min-height:48px;border-radius:9px;box-shadow:0 0 0 1px var(--border) inset}.login-card :deep(.el-input__wrapper.is-focus){box-shadow:0 0 0 1px var(--teal) inset,0 0 0 3px color-mix(in srgb,var(--teal) 12%,transparent)}.login-card .el-button{width:100%;min-height:48px;margin-top:15px;border-radius:9px}.login-card>small{display:block;margin-top:18px;color:var(--quiet);font-size:10px;line-height:1.6;text-align:center}.login-page footer{position:relative;color:var(--quiet);font-size:9px;letter-spacing:.16em}
@media(max-width:800px){.login-page{padding:22px 20px}.login-page__grid{display:block;margin:9vh auto auto}.login-intro{display:none}.login-card{width:min(430px,100%);margin:auto;padding:34px 26px 30px}.login-card h2{font-size:25px}.login-page footer{text-align:center}}
@media(max-width:420px){.login-page__grid{margin-top:7vh}.login-card{padding:30px 22px 26px}.login-page::before{right:-360px}}
</style>
