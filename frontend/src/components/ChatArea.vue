<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { marked } from 'marked'
import { downloadCadFile, designLog, designLogRollback, getHistoryDetail, type DesignLogEntry } from '@/api'

const store = useAppStore()
const chatArea = ref<HTMLElement>()
const dlPanel = ref<HTMLElement>()

// 当前项目的设计日志(每个项目独立管理自己的序号)
const logOpen = ref(false)
const logs = ref<DesignLogEntry[]>([])
const logLoading = ref(false)

watch(() => store.current, async () => {
  logOpen.value = false
  logs.value = []
  if (store.current) await loadLogs()
})
// 发新指令/完成后自动刷新日志(消息区序号依赖 logs,不限于面板打开)
watch([() => store.busy, () => store.messages.length], async ([busy]) => {
  // busy 由 true→false = 一轮设计完成,此时日志已落盘,刷新日志
  if (!busy && store.current) await loadLogs()
})
async function loadLogs() {
  if (!store.current) return
  logLoading.value = true
  try { logs.value = await designLog(store.current) } catch { logs.value = [] }
  finally { logLoading.value = false }
  // 自动滚动到底部(最新一条)
  await nextTick()
  if (dlPanel.value) dlPanel.value.scrollTop = dlPanel.value.scrollHeight
}
async function toggleLogs() {
  logOpen.value = !logOpen.value
  if (logOpen.value) await loadLogs()
}
// 组件挂载时加载日志(此时 store.current 可能已设置,watch 不会触发)
onMounted(async () => { if (store.current) await loadLogs() })
async function rollbackTo(seq: number, instruction: string) {
  if (!store.current) return
  if (!confirm(`从设计日志第 ${seq} 步重新设计？\n\n该步: ${(instruction || '').slice(0, 60)}\n\n模型将恢复到该步开始前的状态，后续指令基于此状态增量修改。`)) return
  try {
    const r = await designLogRollback(store.current, seq)
    alert('✅ ' + (r?.message || `已恢复到第 ${seq} 步`))
    await loadLogs()
  } catch (e: any) {
    alert('回滚失败: ' + (e?.message || e))
  }
}
function logActionLabel(a: string): string {
  const map: Record<string, string> = {
    user_message: '指令', assistant_response: '回复', model_build: '生成', tool_call: '工具', model_clear: '清空',
  }
  return map[a] || a
}
function logTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

watch([() => store.messages, () => store.progress], () => {
  // 滚动容器是外层 .chat-area(overflow-y:auto);chat-inner 随内容撑高 scrollTop 恒 0
  // messages + progress 双触发:设计执行过程中(流式进度行)也实时跟底
  nextTick(() => { if (chatArea.value) chatArea.value.scrollTop = chatArea.value.scrollHeight })
}, { deep: true, flush: 'post' })

function copyMsg(text: string) { navigator.clipboard.writeText(text) }

// 执行过程下钻:展开该轮完整 tool 流水(/history/detail 按需加载)
const expandedSeq = ref<number | null>(null)
const detailRows = ref<any[]>([])
const detailLoading = ref(false)
async function toggleDetail(seqRange: number[]) {
  const key = seqRange[0]
  if (expandedSeq.value === key) { expandedSeq.value = null; return }
  expandedSeq.value = key
  detailLoading.value = true
  try {
    const d = await getHistoryDetail(store.current, seqRange[0], seqRange[1])
    detailRows.value = d.rows || []
  } catch { detailRows.value = [] }
  finally { detailLoading.value = false }
}
async function onLoadEarlier() {
  try { await store.loadEarlierMessages() } catch { /* ignore */ }
 }
function fmtTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function cadFilePath(f: string): string | undefined {
  // 消息 files 带步骤目录(cad/{step_id}/file 或 {step_id}/file)时精确匹配,
  // 链接指向「当轮」结果文件(每步独立目录,不随版本覆盖);
  // 纯文件名(历史旧数据)才降级:同名多版本取最新(时间序靠后)。
  const norm = f.replace(/^cad\//, '')
  const exact = store.cadFiles.find(p => p === norm || p === f)
  if (exact) return exact
  const fn = f.split('/').pop() || f
  const matches = store.cadFiles.filter(p => p === fn || p.endsWith('/' + fn))
  return matches.length ? matches[matches.length - 1] : undefined
}
function cadFileExists(f: string): boolean {
  return !!cadFilePath(f)
}
async function download(f: string) {
  try { await downloadCadFile(store.current, cadFilePath(f) || f) } catch (e: any) { alert(e.message) }
}
// 消息对应的日志序号:按动作类型+时间最近匹配日志条目
// 用户消息→user_message,Anvil回复→assistant_response;匹配不到返回空
function msgSeq(m: any): number | undefined {
  const want = m.role === 'user' ? 'user_message' : 'assistant_response'
  const mt = m.timestamp ? new Date(m.timestamp).getTime() : NaN
  let best: number | undefined
  let bestDiff = Infinity
  for (const lg of logs.value) {
    if (lg.action !== want) continue
    const lt = lg.time ? new Date(lg.time).getTime() : NaN
    if (isNaN(lt)) continue
    const diff = isNaN(mt) ? 0 : Math.abs(lt - mt)
    if (diff < bestDiff) { bestDiff = diff; best = lg.seq }
  }
  // 容差:时间差超 3 分钟视为无对应日志条目(如译码轮次/未执行消息),不挂编号
  return bestDiff <= 180000 ? best : undefined
}
</script>

<template>
  <div class="chat-area" ref="chatArea">
    <div class="design-log-bar">
      <button class="dl-toggle" :class="{ on: logOpen }" @click="toggleLogs" title="当前项目的设计日志(序号=步骤),可从任意一步重新设计">
        📋 设计日志 <span v-if="logs.length" class="dl-count">{{ logs.length }}</span>
      </button>
      <div v-if="logOpen" class="dl-panel" ref="dlPanel">
        <div v-if="logLoading" class="dl-empty">加载中…</div>
        <div v-else-if="!logs.length" class="dl-empty">暂无设计日志</div>
        <table v-else class="dl-table">
          <thead><tr><th>#</th><th>Δ#</th><th>时间</th><th>动作</th><th>设计指示</th><th></th></tr></thead>
          <tbody>
            <tr v-for="lg in logs" :key="lg.seq">
              <td class="dl-seq">{{ lg.seq }}</td>
              <td class="dl-seq">{{ lg.dltq_seq ? 'Δ#' + lg.dltq_seq : '—' }}</td>
              <td class="dl-time">{{ logTime(lg.time) }}</td>
              <td><span class="dl-action">{{ logActionLabel(lg.action) }}</span></td>
              <td class="dl-instruction" :title="lg.instruction">{{ lg.instruction || lg.llm_response }}</td>
              <td><button class="dl-rollback" title="从这一步重新设计" @click="rollbackTo(lg.seq, lg.instruction)">↩ 重设计</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="chat-inner">
      <div v-if="store.histPagesLeft > 0" style="text-align:center;padding:6px">
        <button class="dl-toggle" @click="onLoadEarlier" style="font-size:12px">↑ 加载更早的消息 (还有 {{ store.histPagesLeft }} 页)</button>
      </div>
      <div v-if="store.messages.length === 0" style="padding:20px;text-align:center;color:#999">No messages yet. Type a message to start.</div>
      <div v-for="(m, i) in store.messages" :key="i" class="msg" :class="m.role">
        <div class="role">{{ m.role === 'user' ? 'You' : 'Anvil' }}<span v-if="msgSeq(m)" class="msg-seq" title="设计日志序号(第几步)">#{{ msgSeq(m) }}</span><span v-if="m.timestamp" class="msg-time">{{ fmtTime(m.timestamp) }}</span></div>
        <div v-if="(m.role==='user' || m.role==='assistant') && m.logs" v-for="log in m.logs" class="step-log">{{ log }}</div>
        <div v-if="m.role==='assistant' && m.tools_used && m.tools_used.length" class="tools-line">
          <button class="tools-toggle" @click="toggleDetail(m.seq_range)">⚙ 执行过程({{ m.tools_used.reduce((a:any,t:any)=>a+t.n,0) }} 步)</button>
          <span class="tools-sum">{{ m.tools_used.map((t:any)=>t.tool+(t.n>1?'×'+t.n:'')).join(' · ') }}</span>
          <div v-if="expandedSeq === m.seq_range[0]" class="tools-detail">
            <div v-if="detailLoading" style="padding:8px;color:#999">加载流水…</div>
            <div v-else-if="!detailRows.length" style="padding:8px;color:#999">无明细</div>
            <div v-else class="detail-rows">
              <div v-for="r in detailRows" :key="r._seq" class="detail-row">
                <span class="detail-seq">#{{ r._seq }}</span>
                <span class="detail-type" :class="r.type">{{ r.type }}</span>
                <span class="detail-txt">{{ (r.data?.tool ? r.data.tool+' ' : '') + (r.data?.content || r.data?.result?.status || '') }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="bubble" v-html="marked(m.content)"></div>
        <div v-if="m.role==='assistant' && i===store.messages.length-1 && store.progress" class="progress-line">{{ store.progress || 'Processing...' }}</div>
        <div v-if="m.files && m.files.length" class="msg-files">
          <div v-for="(f, fi) in m.files" :key="fi" class="file-link">
            <span :class="{ 'file-missing': !cadFileExists(f) }" :title="cadFileExists(f) ? '' : '文件已不存在'">{{ f.split('/').pop() }}</span>
            <button v-if="(f.match(/\.stl$/i) || f.match(/\.step$/i) || f.match(/\.stp$/i)) && cadFileExists(f)" class="file-btn-3d" @click="store.openCadFile(cadFilePath(f) || f)" title="3D 预览(内嵌查看,无需下载)">3D</button>
            <button v-if="cadFileExists(f)" class="file-btn-dl" @click="download(f)" title="下载文件">⬇</button>
            <button v-if="!cadFileExists(f)" class="file-btn-gone" disabled title="文件已不存在">—</button>
          </div>
        </div>
        <div v-if="m.role==='user' && !store.busy" class="msg-user-actions">
          <button @click="copyMsg(m.content)" title="复制">📋 Copy</button>
          <button @click="store.resendMsg(m.content)" title="重试">🔄 Retry</button>
        </div>
        <div v-if="m.role==='assistant' && !store.busy && m.content" class="msg-assist-actions">
          <button @click="copyMsg(m.content)" title="复制">📋 Copy</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-area{flex:1;overflow-y:auto;display:flex;flex-direction:column;min-height:0}
.design-log-bar{padding:6px 12px 0;flex-shrink:0}
.dl-toggle{background:#f3f4f6;border:1px solid #e5e5e5;border-radius:6px;padding:4px 12px;font-size:12px;cursor:pointer;color:#555}
.dl-toggle:hover{color:#4f46e5;background:#f0f0ff}
.dl-toggle.on{background:#e0e7ff;color:#4f46e5;border-color:#4f46e5;font-weight:600}
.dl-count{background:#4f46e5;color:#fff;border-radius:8px;padding:0 6px;font-size:10px;margin-left:4px}
.dl-panel{margin-top:6px;border:1px solid #e5e5e5;border-radius:8px;max-height:260px;overflow:auto;background:#fff}
.dl-table{width:100%;border-collapse:collapse;font-size:12px}
.dl-table th{position:sticky;top:0;background:#f8f8f8;font-size:11px;color:#888;text-align:left;padding:6px 8px;border-bottom:1px solid #e5e5e5}
.dl-table td{padding:4px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
.dl-table tr:hover td{background:#f5f7ff}
.dl-seq{width:34px;text-align:center;font-weight:700;color:#4f46e5;font-family:monospace}
.dl-time{white-space:nowrap;color:#888;font-family:monospace;font-size:11px}
.dl-action{display:inline-block;padding:0 6px;border-radius:8px;font-size:10px;background:#eef2ff;color:#4f46e5;white-space:nowrap}
.dl-instruction{max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#333}
.dl-rollback{background:#fff7ed;border:1px solid #fdba74;color:#ea580c;border-radius:4px;padding:1px 8px;font-size:11px;cursor:pointer;white-space:nowrap}
.dl-rollback:hover{background:#ffedd5}
.dl-empty{color:#aaa;text-align:center;padding:14px 0;font-size:12px}
.chat-inner{width:100%;padding:24px 48px 120px 12px;flex:1}
.msg{margin-bottom:20px;max-width:100%}
.msg.user{margin-left:auto}
.msg.assistant{margin-right:auto}
.msg .role{font-size:12px;color:#999;margin-bottom:4px}
.msg-time{font-size:10px;color:#bbb;margin-left:6px;font-family:monospace}
.msg-seq{display:inline-block;background:#4f46e5;color:#fff;border-radius:8px;padding:0 6px;font-size:10px;font-weight:700;margin-left:6px;font-family:monospace}
.msg.user .role{text-align:right}
.msg .bubble{padding:10px 16px;border-radius:12px;line-height:1.7;font-size:14px;white-space:pre-wrap;word-wrap:break-word}
.msg.user .bubble{background:#1677ff;color:#fff;border-bottom-right-radius:4px}
.msg.assistant .bubble{background:#f5f5f5;color:#333;border-bottom-left-radius:4px}
.msg .bubble :deep(p){margin:4px 0}
.msg .bubble :deep(pre){background:rgba(0,0,0,.06);padding:10px;border-radius:6px;overflow-x:auto;font-size:12px;margin:6px 0}
.msg .bubble :deep(code){font-size:12px;background:rgba(0,0,0,.04);padding:1px 4px;border-radius:3px}
.msg .bubble :deep(table){border-collapse:collapse;margin:6px 0;font-size:12px;width:100%}
.msg .bubble :deep(th),.msg .bubble :deep(td){border:1px solid #e5e5e5;padding:4px 8px;text-align:left}
.msg .bubble :deep(th){background:#f9fafb;font-weight:600}
.msg .bubble :deep(img){max-width:100%;border-radius:8px;margin:6px 0}
.msg-user-actions{display:flex;gap:6px;margin-top:4px}
.msg-user-actions button{background:none;border:1px solid #e5e5e5;border-radius:4px;padding:2px 8px;font-size:11px;color:#888;cursor:pointer}
.msg-user-actions button:hover{color:#4f46e5;background:#f0f0ff}
.msg-assist-actions{display:flex;gap:6px;margin-top:4px;opacity:0;transition:opacity .15s}
.msg:hover .msg-assist-actions{opacity:1}
.msg-assist-actions button{background:none;border:1px solid #e5e5e5;border-radius:4px;padding:2px 8px;font-size:11px;color:#888;cursor:pointer}
.msg-assist-actions button:hover{color:#4f46e5;background:#f0f0ff}
.progress-line{font-size:11px;color:#888;padding:2px 0 6px;font-family:monospace}
.step-log{font-size:11px;color:#999;padding:0 0 4px;font-family:monospace;white-space:pre-wrap}
.tools-line{margin:2px 0 6px}
.tools-toggle{font-size:11px;background:#f0f4ff;border:1px solid #d8e0f8;color:#4a6cf7;border-radius:4px;padding:1px 8px;cursor:pointer}
.tools-sum{font-size:11px;color:#8a94a6;margin-left:8px;font-family:monospace}
.tools-detail{margin-top:4px;border-left:2px solid #d8e0f8;padding-left:8px}
.detail-rows{max-height:240px;overflow:auto}
.detail-row{font-size:11px;font-family:monospace;padding:1px 0;display:flex;gap:6px;align-items:baseline}
.detail-seq{color:#bbb;min-width:38px}
.detail-type{min-width:52px;color:#666}
.detail-type.tool{color:#4a6cf7}
.detail-type.user{color:#2a9d4a}
.detail-type.assistant{color:#d9822b}
.detail-txt{color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:520px}
.msg-files{display:flex;gap:6px;margin:4px 0;flex-wrap:wrap}
.file-link{display:inline-flex;align-items:center;gap:4px;background:#f3f4f6;padding:2px 8px;border-radius:4px;font-size:11px}
.file-link span{color:#555;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-btn-3d,.file-btn-dl{background:#4f46e5;color:#fff;border:none;padding:1px 6px;border-radius:3px;font-size:10px;cursor:pointer;text-decoration:none}
.file-btn-3d:hover,.file-btn-dl:hover{background:#4338ca}
.file-missing{color:#bbb;text-decoration:line-through}
.file-btn-gone{background:#e5e5e5;color:#bbb;border:none;padding:1px 6px;border-radius:3px;font-size:10px;cursor:not-allowed}
</style>
