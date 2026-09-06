<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const name = ref('')
const display = ref('')
const parent = ref('')
const inp = ref<HTMLInputElement>()

onMounted(() => inp.value?.focus())

async function create() {
  if (!name.value.trim()) return
  await store.doCreateProject(name.value.trim(), display.value.trim(), parent.value)
  store.showModal = false
  name.value = ''
  display.value = ''
}

function onEnter(e: KeyboardEvent) {
  if (e.isComposing) return
  create()
}
</script>

<template>
  <div class="modal-overlay" @click="store.showModal = false"></div>
  <div class="modal">
    <h3>New Project</h3>
    <input ref="inp" v-model="name" @keydown.enter="onEnter" placeholder="Project name (identifier)..." />
    <input v-model="display" @keydown.enter="onEnter" placeholder="Description (optional)..." style="margin-top:8px" />
    <select v-model="parent" style="margin-top:8px;width:100%;padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px">
      <option value="">顶层项目</option>
      <option v-for="p in store.projects.filter(x=>!x.parent)" :key="p.project_id" :value="p.project_id">└ {{ p.name }}</option>
    </select>
    <div class="modal-actions">
      <button class="cancel" @click="store.showModal = false" title="取消">Cancel</button>
      <button class="primary" @click="create" title="创建项目">Create</button>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.3);z-index:100}
.modal{padding:20px;background:#fff;border-radius:12px;width:360px;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:120;box-shadow:0 8px 40px rgba(0,0,0,.2)}
.modal h3{font-size:15px;font-weight:600;margin-bottom:12px}
.modal input{width:100%;padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;outline:none;margin-bottom:12px}
.modal input:focus{border-color:#4f46e5}
.modal-actions{display:flex;gap:8px;justify-content:flex-end}
.modal-actions button{padding:8px 20px;border-radius:8px;font-size:13px;cursor:pointer}
.modal-actions .primary{background:#4f46e5;color:#fff;border:none}
.modal-actions .cancel{background:#f3f4f6;color:#333;border:1px solid #d1d5db}
</style>
