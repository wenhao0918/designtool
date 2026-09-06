<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import { logout } from '@/api'
const store = useAppStore()
</script>

<template>
  <div class="top">
    <h2>{{ store.currentProject.name }}</h2>
    <span v-if="store.phase" class="phase-tag">{{ store.phase }}</span>
    <span class="spacer"></span>
    <button class="logout-btn" @click="logout()" title="退出登录">🚪</button>
  </div>
</template>

<style scoped>
.top{display:flex;align-items:center;padding:0 20px;height:48px;border-bottom:1px solid #e5e5e5;flex-shrink:0;gap:12px}
.top h2{font-size:13px;font-weight:600;color:#111}
.phase-tag{font-size:10px;color:#6b7280;background:#f3f4f6;padding:2px 8px;border-radius:6px}
.spacer{flex:1}
.logout-btn{font-size:16px;background:none;border:none;cursor:pointer;padding:4px 6px;opacity:0.5}
.logout-btn:hover{opacity:1}
</style>
