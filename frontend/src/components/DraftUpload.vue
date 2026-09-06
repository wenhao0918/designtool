<script setup lang="ts">
import { ref } from 'vue'

defineOptions({ name: 'DraftUpload' })

const loading = ref(false)
const error = ref('')
const svgContent = ref('')
const meta = ref<any>(null)
const fileName = ref('')
const dragOver = ref(false)

const ACCEPT = '.step,.stp,.iges,.igs,.brep'

async function upload(file: File) {
  if (!file) return
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!ACCEPT.includes(ext)) {
    error.value = `不支持的格式 ${ext},请上传 STEP/IGES/BREP 文件`
    return
  }
  loading.value = true
  error.value = ''
  svgContent.value = ''
  meta.value = null
  fileName.value = file.name
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('out_dir', '/tmp')
    fd.append('title', file.name.replace(/\.[^.]+$/, ''))
    fd.append('project', 'upload')
    const r = await fetch('/draft-api/api/drawing/from-file', { method: 'POST', body: fd })
    const data = await r.json()
    if (!r.ok || data.error) {
      throw new Error(data.error || `HTTP ${r.status}`)
    }
    // 获取 SVG 内容
    const svgR = await fetch('/draft-api' + data.svg.replace('/tmp', '/api/file'))
    // DraftEngine 的 svg 是服务器路径,需要另一个接口返回内容
    // 简化:直接调 from-path 返回 svg 内容?不,DraftEngine 返回的是路径。
    // 这里改为:让后端返回 svg 内容。
    meta.value = data.meta
    await loadSvg(file, data)
  } catch (e: any) {
    error.value = '生成失败: ' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

async function loadSvg(file: File, data: any) {
  // 方式1:如果后端返回了 svg_content
  if (data.svg_content) {
    svgContent.value = data.svg_content
    return
  }
  // 方式2:服务器路径 → 通过 from-path 再拿一次(不优雅)
  // 改为:直接用本地文件再次上传并请求 svg? 最简单:调 /draft-api 的文件服务
  // 这里用 fetch 服务器文件(如果 API 提供了)
  error.value = '后端未返回 SVG 内容(需 api 返回 svg_content)'
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) upload(input.files[0])
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  if (e.dataTransfer?.files.length) upload(e.dataTransfer.files[0])
}
</script>

<template>
  <div class="draft-upload">
    <div
      class="drop-zone"
      :class="{ over: dragOver, loading }"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="onDrop"
      @click="($refs.fileInput as any)?.click()"
    >
      <input ref="fileInput" type="file" :accept="ACCEPT" style="display:none" @change="onFile" />
      <div v-if="loading" class="dz-loading">⏳ 正在生成工程图纸...</div>
      <template v-else>
        <div class="dz-icon">📐</div>
        <p class="dz-title">点击或拖拽 3D 模型文件到此处</p>
        <p class="dz-sub">支持 STEP / IGES / BREP,自动生成三视图工程图纸</p>
      </template>
    </div>

    <div v-if="error" class="draft-err">{{ error }}</div>

    <div v-if="fileName && !error" class="draft-file">📄 {{ fileName }}</div>

    <div v-if="svgContent" class="draft-result">
      <div class="draft-svg" v-html="svgContent"></div>
      <div v-if="meta" class="draft-meta">
        <h4>结构化信息 (meta)</h4>
        <p><b>零件类型:</b> {{ meta.part_type }} <span v-if="meta.main_axis">/ 主轴 {{ meta.main_axis }}</span></p>
        <p><b>外形尺寸:</b> {{ meta.bounding_box?.L }} × {{ meta.bounding_box?.W }} × {{ meta.bounding_box?.H }} mm</p>
        <p v-if="meta.holes?.length"><b>孔特征:</b></p>
        <ul v-if="meta.holes?.length">
          <li v-for="(h, i) in meta.holes" :key="i">
            Φ{{ h.dia }} <span class="axis" :class="'ax-' + h.axis">{{ h.axis }}向</span>
            中心({{ h.center.join(', ') }}) 深{{ h.depth }}
            <span class="subtype">{{ h.subtype }}</span>
          </li>
        </ul>
        <p v-if="meta.dimensions?.length"><b>尺寸标注:</b> {{ meta.dimensions.join(' · ') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.draft-upload{flex:1;display:flex;flex-direction:column;gap:12px;overflow:auto;padding:4px}
.drop-zone{border:2px dashed #cbd5e1;border-radius:12px;padding:36px 20px;text-align:center;cursor:pointer;transition:all .2s;background:#fafbfc}
.drop-zone:hover,.drop-zone.over{border-color:#4f46e5;background:#eef2ff}
.drop-zone.loading{opacity:.6;cursor:wait}
.dz-icon{font-size:40px;margin-bottom:8px}
.dz-title{font-size:15px;font-weight:600;color:#333;margin:0 0 4px}
.dz-sub{font-size:12px;color:#888;margin:0}
.dz-loading{font-size:14px;color:#4f46e5}
.draft-err{color:#dc2626;background:#fef2f2;border:1px solid #fecaca;padding:10px 14px;border-radius:8px;font-size:13px}
.draft-file{font-size:12px;color:#666;background:#f1f5f9;padding:6px 12px;border-radius:6px;display:inline-block;align-self:flex-start}
.draft-result{display:flex;flex-direction:column;gap:12px}
.draft-svg{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:8px;overflow:auto}
.draft-svg :deep(svg){width:100%;height:auto;background:#fff}
.draft-meta{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;font-size:12px;color:#334155}
.draft-meta h4{margin:0 0 8px;font-size:13px;color:#0f172a}
.draft-meta p{margin:4px 0}
.draft-meta ul{margin:4px 0 4px 18px;padding:0}
.draft-meta li{margin:2px 0}
.axis{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;font-weight:600}
.ax-X{background:#fee2e2;color:#b91c1c}
.ax-Y{background:#dbeafe;color:#1d4ed8}
.ax-Z{background:#dcfce7;color:#15803d}
.subtype{font-size:11px;color:#888}
</style>
