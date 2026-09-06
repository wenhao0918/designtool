<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { getDocContent } from '@/api'
import { marked } from 'marked'

const store = useAppStore()
const docContent = ref('')
const sections = [
  { key: 'notes', label: 'Notes' },
  { key: 'decisions', label: 'Decisions' },
  { key: 'calculations', label: 'Calcs' },
  { key: 'changelog', label: 'Changes' }
]

const files = computed(() => store.docs[store.docSection] || [])

function formatName(f: string) {
  return f.replace(/\.md$/, '').replace(/^\d{8}_\d{6}_/, '').replace(/_/g, ' ')
}

async function selectFile(f: string) {
  store.docFile = f
  docContent.value = await getDocContent(store.current, store.docSection, f)
}

watch(() => store.docSection, () => {
  if (files.value.length) selectFile(files.value[0])
})

watch(() => store.docOpen, (v) => {
  if (v && files.value.length && !store.docFile) selectFile(files.value[0])
})
</script>

<template>
  <div class="doc-overlay" @click="store.closeDocs()"></div>
  <div class="doc-panel">
    <div class="doc-hd">
      <button class="back" @click="store.closeDocs()" title="←Back">← Back</button>
      <h3>{{ store.currentProject.name }}</h3>
      <div class="nav">
        <button v-for="s in sections" :key="s.key" :title="s.label" :class="{ on: s.key === store.docSection }"
          @click="store.docSection = s.key">{{ s.label }}</button>
      </div>
    </div>
    <div class="doc-body-wrap">
      <div class="doc-tree">
        <div v-for="f in files" :key="f" class="doc-tree-item"
          :class="{ on: f === store.docFile }" @click="selectFile(f)">
          {{ formatName(f) }}
        </div>
        <div v-if="!files.length" style="padding:12px;color:#999;font-size:12px">No documents</div>
      </div>
      <div class="doc-body" v-html="marked(docContent)"></div>
    </div>
  </div>
</template>

<style scoped>
.doc-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.3);z-index:100}
.doc-panel{position:fixed;top:0;right:0;width:60vw;height:100%;background:#fff;z-index:110;display:flex;flex-direction:column;box-shadow:-4px 0 20px rgba(0,0,0,.1)}
.doc-hd{display:flex;align-items:center;padding:10px 16px;border-bottom:1px solid #e5e5e5;gap:8px;flex-shrink:0}
.doc-hd .back{background:none;border:none;font-size:18px;cursor:pointer;padding:4px 8px;color:#666;border-radius:4px}
.doc-hd .back:hover{color:#333;background:#f5f5f5}
.doc-hd h3{font-size:14px;font-weight:600}
.doc-hd .nav{display:flex;gap:4px;margin-left:auto}
.doc-hd .nav button{padding:4px 10px;font-size:11px;border:1px solid #d1d5db;background:#fff;border-radius:4px;cursor:pointer;color:#666}
.doc-hd .nav button.on{background:#4f46e5;color:#fff;border-color:#4f46e5}
.doc-body-wrap{display:flex;flex:1;overflow:hidden}
.doc-tree{width:200px;border-right:1px solid #e5e5e5;overflow-y:auto;padding:8px 0;flex-shrink:0}
.doc-tree-item{padding:6px 12px;font-size:12px;color:#555;cursor:pointer}
.doc-tree-item:hover{background:#f5f5f5;color:#111}
.doc-tree-item.on{color:#4f46e5;font-weight:600;background:#f0f0ff}
.doc-body{flex:1;overflow-y:auto;padding:20px 24px;font-size:14px;line-height:1.75}
.doc-body :deep(h1){font-size:20px;font-weight:700;margin-bottom:12px}
.doc-body :deep(h2){font-size:16px;font-weight:600;margin:18px 0 8px}
.doc-body :deep(p){margin:5px 0;color:#444}
</style>
