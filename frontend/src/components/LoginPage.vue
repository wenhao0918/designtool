<script setup lang="ts">
import { ref } from "vue"
import * as api from "@/api"

const mode = ref<'login' | 'register'>('login')
const username = ref("")
const password = ref("")
const displayName = ref("")
const error = ref("")
const loading = ref(false)

async function doLogin() {
  error.value = ""
  if (!username.value || !password.value) {
    error.value = "请输入用户名和密码"
    return
  }
  loading.value = true
  try {
    await api.login(username.value, password.value)
    window.location.reload()
  } catch (e: any) {
    error.value = e.message || "登录失败"
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  error.value = ""
  if (!username.value || !password.value) {
    error.value = "请输入用户名和密码"
    return
  }
  if (password.value.length < 4) {
    error.value = "密码至少4位"
    return
  }
  loading.value = true
  try {
    await api.register(username.value, password.value, displayName.value)
    window.location.reload()  // 注册成功自动登录并进入
  } catch (e: any) {
    error.value = e.message || "注册失败"
  } finally {
    loading.value = false
  }
}

function handleKey(e: KeyboardEvent) {
  if (e.key === "Enter") mode.value === 'login' ? doLogin() : doRegister()
}
</script>

<template>
  <div class="login-wrapper">
    <div class="login-card">
      <div class="login-logo">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect x="4" y="20" width="40" height="18" rx="3" fill="#2563eb" opacity="0.3"/>
          <rect x="8" y="8" width="32" height="32" rx="4" fill="#2563eb" opacity="0.6"/>
          <rect x="12" y="12" width="24" height="24" rx="3" fill="#2563eb"/>
          <text x="24" y="30" text-anchor="middle" fill="white" font-size="14" font-weight="bold">A</text>
        </svg>
      </div>
      <h2>Anvil</h2>
      <p class="login-sub">AI 机械设计工具</p>
      <div class="login-form">
        <template v-if="mode === 'login'">
          <input v-model="username" placeholder="用户名" @keyup="handleKey" autofocus />
          <input v-model="password" type="password" placeholder="密码" @keyup="handleKey" />
        </template>
        <template v-else>
          <input v-model="username" placeholder="用户名(至少2字符)" @keyup="handleKey" autofocus />
          <input v-model="displayName" placeholder="显示名(可选)" @keyup="handleKey" />
          <input v-model="password" type="password" placeholder="密码(至少4位)" @keyup="handleKey" />
          <p class="login-register-hint">注册后默认「访客」权限,由管理员提升</p>
        </template>
        <p v-if="error" class="login-error">{{ error }}</p>
        <button @click="mode === 'login' ? doLogin() : doRegister()" :disabled="loading" title="登录">
          {{ loading ? "请稍候..." : mode === 'login' ? "登录" : "注册" }}
        </button>
      </div>
      <p class="login-tip">
        <a href="#" @click.prevent="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? '没有账号? 注册' : '已有账号? 登录' }}
        </a>
      </p>
      <p class="login-tip" v-if="mode === 'login'">默认账号: admin / anvil123</p>
    </div>
  </div>
</template>

<style scoped>
.login-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  background: white;
  border-radius: 12px;
  padding: 40px;
  width: 360px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.2);
  text-align: center;
}
.login-logo { margin-bottom: 12px; }
h2 { font-size: 24px; font-weight: 600; margin-bottom: 4px; color: #1a1a1a; }
.login-sub { font-size: 14px; color: #888; margin-bottom: 24px; }
.login-form input {
  display: block;
  width: 100%;
  padding: 10px 14px;
  margin-bottom: 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}
.login-form input:focus { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,0.15); }
.login-error { color: #dc2626; font-size: 13px; margin-bottom: 8px; }
.login-register-hint { font-size: 11px; color: #999; margin: -4px 0 8px; text-align: center; }
.login-tip a { color: #667eea; text-decoration: none; }
.login-tip a:hover { text-decoration: underline; }
.login-form button {
  width: 100%;
  padding: 10px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
  font-weight: 500;
}
.login-form button:hover { background: #1d4ed8; }
.login-form button:disabled { opacity: 0.6; cursor: not-allowed; }
.login-tip { font-size: 12px; color: #aaa; margin-top: 16px; }
</style>
