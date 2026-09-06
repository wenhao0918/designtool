<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const text = ref('')
const fileInput = ref<HTMLInputElement>()

const emit = defineEmits<{ (e: 'goto-sketch'): void }>()

// 录音:按住录音 → 松开自动转文字替换输入框内容
const recording = ref(false)
let mediaRecorder: any = null
let mediaChunks: Blob[] = []
let mediaStream: any = null
let voiceAllowed = true
;(async () => {
  try {
    const { myTools } = await import('@/api')
    const t = await myTools()
    voiceAllowed = t.some(x => x.code === 'voice')
  } catch { /* 默认允许 */ }
})()

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

function send() {
  if (!text.value.trim()) return
  store.send(text.value.trim())
  text.value = ''
}

function clearText() {
  text.value = ''
}

function toggleSketch() {
  emit('goto-sketch')
}

async function onRecordStart() {
  if (!voiceAllowed) { alert('你没有语音工具权限,请联系管理员授权'); return }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaChunks = []
    const MR = (window as any).MediaRecorder
    if (!MR) { mediaStream.getTracks().forEach((t: any) => t.stop()); alert('浏览器不支持录音'); return }
    mediaRecorder = new MR(mediaStream)
    mediaRecorder.ondataavailable = (e: any) => { if (e.data.size) mediaChunks.push(e.data) }
    mediaRecorder.onstop = async () => {
      mediaStream.getTracks().forEach((t: any) => t.stop())
      const blob = new Blob(mediaChunks, { type: mediaRecorder.mimeType || 'audio/webm' })
      recording.value = false
      // 转文字并替换输入框内容
      try {
        const fd = new FormData()
        fd.append('file', blob, 'speech.webm')
        const r = await fetch('/voice-api/recognize', { method: 'POST', body: fd })
        const j = await r.json()
        if (j.text) text.value = j.text  // 替换输入框内容,用户可修改后发送
      } catch { /* 转写失败忽略 */ }
    }
    mediaRecorder.start()
    recording.value = true
  } catch { alert('无法访问麦克风') }
}

function onRecordEnd() {
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop()
}
</script>

<template>
  <div class="in-area">
    <div class="in-box">
      <!-- 输入框 + 右侧功能按钮列(全部右对齐,高度跟随输入框) -->
      <div class="in-box-row">
        <textarea v-model="text" :disabled="store.busy" @keydown="onKeydown"
          placeholder="输入设计需求... 按住 🎤 语音输入, Shift+Enter 换行"
          rows="2" class="in-textarea" :class="{ recording }"></textarea>
        <div class="op-col">
          <button class="tbtn" :class="{ active: store.encoderMode }" title="译码模式（自然语言→纯数字串）" :disabled="store.busy" @click="store.toggleTranslator()">电</button>
          <button class="tbtn" title="手绘草图" :disabled="store.busy" @click="toggleSketch">✏️</button>
          <button class="tbtn" title="清除输入" :disabled="!text" @click="clearText">🗑</button>
          <button class="btn btn-rec" :class="{ recording }"
            :title="recording ? '松开结束录音并转文字' : '按住录音(松开自动转文字)'"
            :disabled="store.busy"
            @pointerdown.prevent="onRecordStart" @pointerup="onRecordEnd" @pointerleave="onRecordEnd">🎤</button>
          <button v-if="!store.busy" class="btn btn-send" title="发送 (Enter)" @click="send">↑</button>
          <button v-else class="btn btn-stop" title="停止生成" @click="store.stopSend()">■</button>
        </div>
      </div>
      <div class="in-hint">Enter 发送 · Shift+Enter 换行 · 🎤 按住录音自动转文字</div>
    </div>
  </div>
</template>

<style scoped>
.in-area{border-top:1px solid #e5e5e5;padding:8px 0;flex-shrink:0;background:#fff}
.in-box{width:100%;padding:0 12px;margin:0}
.in-box-row{display:flex;gap:8px;align-items:stretch}
.in-textarea{flex:1;min-width:0;border:1px solid #d1d5db;border-radius:8px;padding:8px 12px;font-size:13px;resize:vertical;outline:none;font-family:inherit;line-height:1.5;min-height:52px;max-height:220px}
.in-textarea:focus{border-color:#4f46e5}
.in-textarea.recording{border-color:#dc2626;box-shadow:0 0 0 2px rgba(220,38,38,.15)}
/* 功能按钮列:右侧一列,高度跟随输入框,按钮纵向分布 */
.op-col{display:flex;flex-direction:column;gap:4px;flex-shrink:0;align-items:stretch}
.op-col .tbtn,.op-col .btn{flex:1;min-height:32px;display:flex;align-items:center;justify-content:center}
.tbtn{background:#fff;border:1px solid #d1d5db;border-radius:6px;padding:4px 10px;font-size:13px;cursor:pointer;color:#4f46e5}
.tbtn:hover{background:#eef2ff;border-color:#c7d2fe}
.tbtn:disabled{opacity:.5;cursor:default}
.tbtn.active{background:#4f46e5;color:#fff;border-color:#4338ca}
.btn{border-radius:8px;cursor:pointer;font-size:14px;line-height:1;border:1px solid transparent}
.btn:disabled{opacity:.5;cursor:default}
.btn-send{background:#4f46e5;color:#fff}
.btn-send:hover{background:#4338ca}
.btn-stop{background:#dc2626;color:#fff}
.btn-rec{background:#fff;color:#dc2626;border-color:#fecaca;font-size:15px}
.btn-rec:hover{background:#fee2e2}
.btn-rec.recording{background:#dc2626;color:#fff;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.in-hint{font-size:10px;color:#bbb;margin-top:4px}
</style>
