<script setup lang="ts">
import { useAppStore } from '@/stores/app'

const store = useAppStore()
</script>

<template>
  <div class="side">
    <div class="side-hd"><h1>Anvil</h1><small>AI Mechanical Design</small></div>
    <div class="side-projects">
      <div v-if="store.projects.length === 0" style="padding:12px;text-align:center;color:#999;font-size:12px">Loading projects...</div>
      <div v-for="p in store.projects" :key="p.name"
        class="proj-item" :class="{active: p.name === store.current}"
        @click="store.selectProject(p.name)">
        <span>{{ p.display || p.name }}</span>
        <span v-if="p.phase" class="phase">{{ p.phase }}</span>
      </div>
    </div>
    <div class="new-proj" @click="store.showModal = true">+ New Project</div>
  </div>
</template>

<style scoped>
.side{width:260px;background:#f5f5f5;border-right:1px solid #e5e5e5;display:flex;flex-direction:column;flex-shrink:0}
.side-hd{padding:16px 16px 12px;border-bottom:1px solid #e5e5e5}
.side-hd h1{font-size:16px;font-weight:700;color:#4f46e5}
.side-hd small{font-size:10px;color:#999}
.side-projects{flex:1;overflow-y:auto;padding:4px 0}
.proj-item{display:flex;align-items:center;padding:8px 12px;margin:1px 0;border-radius:6px;cursor:pointer;font-size:13px;color:#333;gap:8px}
.proj-item:hover{background:#e8e8ea}
.proj-item.active{background:#e0e7ff;color:#4f46e5;font-weight:600}
.proj-item .phase{font-size:10px;color:#999;margin-left:auto}
.new-proj{margin:8px 12px;padding:8px;border:1px dashed #d1d5db;border-radius:8px;text-align:center;font-size:12px;color:#6b7280;cursor:pointer}
.new-proj:hover{border-color:#4f46e5;color:#4f46e5;background:#fff}
</style>
