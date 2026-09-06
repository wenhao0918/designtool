<script setup lang="ts">
import { ref } from 'vue'

defineOptions({ name: 'OcrTool' })

const imageUrl = ref('')
const text = ref('')
const items = ref<{ text: string; conf: number }[]>([])
const loading = ref(false)
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

function pickFile() { fileInput.value?.click() }

function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  imageUrl.value = URL.createObjectURL(file)
  error.value = ''
  doOcr(file)
  input.value = ''
}

async function doOcr(file: File) {
  loading.value = true
  error.value = ''
  text.value = ''
  items.value = []
  try {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch('/ocr-api/ocr', { method: 'POST', body: fd })
    const j = await r.json()
    if (!r.ok) { error.value = j?.error || 'OCR 失败'; return }
    text.value = j.text || '(未识别到文字)'
    items.value = j.items || []
  } catch (e: any) {
    error.value = 'OCR 服务不可用: ' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

function copyText() {
  navigator.clipboard.writeText(text.value)
}
</script>

<template>
  <div class="ocr-tool">
    <div class="ocr-hd">
      <h3>🔍 OCR 文字识别</h3>
      <span class="ocr-sub">本地免费识别(中英文)· 图纸/截图/物料图片转文字</span>
      <button class="btn-pick" @click="pickFile" title="📷选择图片">📷 选择图片</button>
      <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onFilePicked" />
    </div>

    <div class="ocr-body">
      <div class="ocr-preview">
        <img v-if="imageUrl" :src="imageUrl" class="ocr-img" />
        <div v-else class="ocr-empty">选择图片开始识别<br /><small>支持 PNG/JPG/PDF截图等</small></div>
        <div v-if="loading" class="ocr-loading">识别中...</div>
      </div>
      <div class="ocr-result">
        <div class="result-hd">
          <span>识别结果</span>
          <button class="btn-copy" @click="copyText" :disabled="!text" title="复制">📋 复制</button>
        </div>
        <textarea v-model="text" class="ocr-text" readonly placeholder="识别出的文字将显示在这里..."></textarea>
        <div v-if="items.length" class="ocr-items">
          <div v-for="(it, i) in items" :key="i" class="ocr-item">
            <span class="item-text">{{ it.text }}</span>
            <span class="item-conf">{{ (it.conf * 100).toFixed(0) }}%</span>
          </div>
        </div>
        <p v-if="error" class="ocr-error">{{ error }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ocr-tool{flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;padding:16px 20px}
.ocr-hd{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.ocr-hd h3{font-size:16px;font-weight:700;color:#333;margin:0}
.ocr-sub{font-size:11px;color:#999}
.btn-pick{margin-left:auto;background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:12px;cursor:pointer}
.btn-pick:hover{background:#4338ca}
.ocr-body{flex:1;display:flex;gap:16px;min-height:0}
.ocr-preview{flex:1;border:1px solid #e5e5e5;border-radius:8px;display:flex;align-items:center;justify-content:center;background:#fafafa;min-height:0;overflow:auto;position:relative}
.ocr-img{max-width:100%;max-height:100%;object-fit:contain}
.ocr-empty{color:#aaa;text-align:center;font-size:14px}
.ocr-empty small{font-size:11px;color:#ccc}
.ocr-loading{position:absolute;inset:0;background:rgba(255,255,255,.85);display:flex;align-items:center;justify-content:center;color:#4f46e5;font-size:14px}
.ocr-result{flex:1;display:flex;flex-direction:column;min-height:0}
.result-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.result-hd span{font-size:13px;font-weight:600;color:#333}
.btn-copy{background:#fff;border:1px solid #d0d0d4;border-radius:6px;padding:3px 10px;font-size:11px;cursor:pointer}
.btn-copy:disabled{opacity:.5;cursor:not-allowed}
.ocr-text{flex:1;min-height:0;border:1px solid #e5e5e5;border-radius:8px;padding:10px;font-size:13px;resize:none;line-height:1.6}
.ocr-items{max-height:160px;overflow-y:auto;margin-top:8px;border:1px solid #e5e5e5;border-radius:6px}
.ocr-item{display:flex;align-items:center;justify-content:space-between;padding:4px 10px;font-size:12px;border-bottom:1px solid #f0f0f0}
.ocr-item .item-text{flex:1;color:#333}
.ocr-item .item-conf{font-size:10px;color:#999}
.ocr-error{color:#dc2626;font-size:12px;margin-top:8px}
</style>
