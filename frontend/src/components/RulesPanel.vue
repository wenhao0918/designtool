<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const dirty = ref(false)

function onInput(e: Event) {
  store.rulesContent = (e.target as HTMLTextAreaElement).value
  dirty.value = true
}

async function save() {
  await store.doSaveRules()
  dirty.value = false
}
</script>

<template>
  <div class="rules-overlay" @click="store.closeRules()"></div>
  <div class="rules-panel">
    <div class="rules-hd">
      <h3>📝 Design Rules</h3>
      <span style="font-size:11px;color:#999;flex:1">Injected as priority prompt</span>
      <button class="close" @click="store.closeRules()" title="关闭">×</button>
    </div>
    <div class="rules-body">
      <div class="hint">Write design rules in plain text or markdown.</div>
      <textarea :value="store.rulesContent" @input="onInput" placeholder="Enter rules..."></textarea>
      <div class="actions">
        <span v-if="dirty" style="font-size:12px;color:#f59e0b">Unsaved</span>
        <button class="cancel" @click="store.closeRules()" title="取消">Cancel</button>
        <button class="primary" title="保存规则" @click="save">Save Rules</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rules-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.3);z-index:100}
.rules-panel{position:fixed;top:0;right:0;width:50vw;height:100%;background:#fff;z-index:110;display:flex;flex-direction:column;box-shadow:-4px 0 20px rgba(0,0,0,.1)}
.rules-hd{display:flex;align-items:center;padding:10px 16px;border-bottom:1px solid #e5e5e5;gap:8px;flex-shrink:0}
.rules-hd h3{font-size:14px;font-weight:600}
.rules-hd .close{background:none;border:none;font-size:22px;cursor:pointer;color:#888;padding:0 6px}
.rules-hd .close:hover{color:#333}
.rules-body{flex:1;display:flex;flex-direction:column;padding:16px}
.rules-body textarea{flex:1;width:100%;padding:12px;border:1px solid #d1d5db;border-radius:8px;font-size:13px;font-family:monospace;line-height:1.6;resize:none;outline:none}
.rules-body textarea:focus{border-color:#4f46e5}
.rules-body .hint{font-size:11px;color:#999;margin-bottom:8px}
.rules-body .actions{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
.rules-body .actions button{padding:8px 20px;border-radius:8px;font-size:13px;cursor:pointer}
.rules-body .actions .primary{background:#4f46e5;color:#fff;border:none}
.rules-body .actions .cancel{background:#f3f4f6;color:#333;border:1px solid #d1d5db}
</style>
