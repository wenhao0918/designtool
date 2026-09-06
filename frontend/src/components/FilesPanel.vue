<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { downloadCadFile, drawingUrl } from '@/api'

const store = useAppStore()

async function download(f: string) {
  try { await downloadCadFile(store.current, f) } catch (e: any) { alert(e.message) }
}

function formatSize(f: string) {
  // Show type badge only; size needs HEAD request, skip for simplicity
  return f.endsWith('.step') ? 'STEP' : f.endsWith('.stl') ? 'STL' : f.split('.').pop()?.toUpperCase() || ''
}

// 工程图纸(STEP → 三视图 SVG)
const drawingOpen = ref(false)
const drawingSvg = ref('')
const drawingFile = ref('')
const drawingErr = ref('')
async function openDrawing(f: string) {
  drawingErr.value = ''
  drawingFile.value = f
  drawingOpen.value = true
  try {
    const url = await drawingUrl(store.current, f, 'svg')
    const r = await fetch(url, { headers: { Authorization: 'Bearer ' + localStorage.getItem('anvil_token') } })
    if (!r.ok) {
      const t = await r.text()
      drawingErr.value = '图纸生成失败: ' + (t.slice(0, 120) || r.status)
      return
    }
    drawingSvg.value = await r.text()
  } catch (e: any) {
    drawingErr.value = '图纸生成失败: ' + (e?.message || e)
  }
}
async function downloadPdf() {
  const url = await drawingUrl(store.current, drawingFile.value, 'pdf')
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + localStorage.getItem('anvil_token') } })
  if (!r.ok) { alert('PDF 生成失败: ' + r.status); return }
  const blob = await r.blob()
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u
  a.download = drawingFile.value.split('/').pop()!.replace('.step', '.pdf').replace('.stp', '.pdf')
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(u)
}
</script>

<template>
  <div class="files-overlay" @click="store.closeFiles()"></div>
  <div class="files-panel">
    <div class="files-hd">
      <h3>📁 生成文件</h3>
      <span class="files-sub">{{ store.cadFiles.length }} files</span>
      <button class="refresh" @click="store.loadCadFiles()" title="刷新">⟳</button>
      <button class="close" @click="store.closeFiles()">×</button>
    </div>
    <div class="files-body">
      <div v-if="!store.cadFiles.length" class="files-empty">
        <p>暂无生成文件</p>
        <span>让 AI 构建模型后，STEP/STL 文件会出现在这里</span>
      </div>
      <div v-else class="file-list">
        <div v-for="f in store.cadFiles" :key="f" class="file-item">
          <span class="file-type">{{ formatSize(f) }}</span>
          <span class="file-name" :title="f">{{ f }}</span>
          <div class="file-actions">
            <button v-if="f.endsWith('.stl')" class="act-3d" title="3D 查看" @click="store.openCadFile(f)">3D</button>
            <button v-if="f.endsWith('.step') || f.endsWith('.stp')" class="act-draw" title="工程图纸(三视图)" @click="openDrawing(f)">📐</button>
            <button class="act-dl" @click="download(f)" title="下载">⬇</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 工程图纸弹层 -->
  <div v-if="drawingOpen" class="drawing-mask" @click.self="drawingOpen = false">
    <div class="drawing-modal">
      <div class="drawing-hd">
        <h3>📐 工程图纸 <span class="drawing-file">{{ drawingFile }}</span></h3>
        <button class="drawing-pdf" @click="downloadPdf" title="下载 PDF">⬇ PDF</button>
        <button class="drawing-close" @click="drawingOpen = false">×</button>
      </div>
      <div v-if="drawingErr" class="drawing-err">{{ drawingErr }}</div>
      <div v-else-if="!drawingSvg" class="drawing-loading">图纸生成中...</div>
      <div v-else class="drawing-body" v-html="drawingSvg"></div>
    </div>
  </div>
</template>

<style scoped>
.files-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.3);z-index:100}
.files-panel{position:fixed;top:0;right:0;width:50vw;height:100%;background:#fff;z-index:110;display:flex;flex-direction:column;box-shadow:-4px 0 20px rgba(0,0,0,.1)}
.files-hd{display:flex;align-items:center;padding:10px 16px;border-bottom:1px solid #e5e5e5;gap:8px;flex-shrink:0}
.files-hd h3{font-size:14px;font-weight:600}
.files-sub{font-size:11px;color:#999;background:#f3f4f6;padding:2px 8px;border-radius:6px}
.files-hd .refresh{background:none;border:none;font-size:16px;cursor:pointer;color:#888;padding:0 4px;margin-left:auto}
.files-hd .refresh:hover{color:#4f46e5}
.files-hd .close{background:none;border:none;font-size:22px;cursor:pointer;color:#888;padding:0 6px}
.files-hd .close:hover{color:#333}
.files-body{flex:1;overflow-y:auto;padding:16px}
.files-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#999;gap:8px}
.files-empty p{font-size:14px}
.files-empty span{font-size:11px;color:#bbb}
.file-list{display:flex;flex-direction:column;gap:6px}
.file-item{display:flex;align-items:center;padding:8px 12px;border:1px solid #e5e5e5;border-radius:8px;gap:10px}
.file-item:hover{background:#fafafa}
.file-type{font-size:10px;font-weight:600;color:#4f46e5;background:#e0e7ff;padding:2px 6px;border-radius:4px;flex-shrink:0;min-width:36px;text-align:center}
.file-name{flex:1;font-size:12px;color:#555;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-actions{display:flex;gap:6px;flex-shrink:0}
.act-3d{background:#4f46e5;color:#fff;border:none;padding:3px 10px;border-radius:4px;font-size:11px;cursor:pointer}
.act-3d:hover{background:#4338ca}
.act-dl{background:#f3f4f6;color:#555;text-decoration:none;padding:3px 8px;border-radius:4px;font-size:12px;cursor:pointer}
.act-dl:hover{background:#e5e5e5}
.act-draw{background:#0d9488;color:#fff;border:none;padding:3px 10px;border-radius:4px;font-size:11px;cursor:pointer}
.act-draw:hover{background:#0f766e}
.drawing-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:200;display:flex;align-items:center;justify-content:center}
.drawing-modal{background:#fff;border-radius:10px;width:min(900px,92vw);height:min(680px,90vh);display:flex;flex-direction:column;box-shadow:0 10px 40px rgba(0,0,0,.3)}
.drawing-hd{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #e5e5e5}
.drawing-hd h3{font-size:15px;margin:0;font-weight:600}
.drawing-file{font-size:11px;color:#999;font-family:monospace;margin-left:6px}
.drawing-pdf{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:12px;cursor:pointer;margin-left:auto}
.drawing-close{background:none;border:none;font-size:20px;cursor:pointer;color:#999}
.drawing-close:hover{color:#333}
.drawing-err{color:#dc2626;padding:20px;text-align:center;font-size:13px}
.drawing-loading{color:#999;padding:40px;text-align:center;font-size:13px}
.drawing-body{flex:1;overflow:auto;padding:12px;background:#fafafa}
.drawing-body :deep(svg){width:100%;height:auto;background:#fff;border:1px solid #e5e5e5}
</style>
