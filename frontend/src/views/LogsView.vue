<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminLogs, designLogRollback, type AdminLogs } from '@/api'

defineOptions({ name: 'LogsView' })

const tab = ref<'downloads' | 'design'>('downloads')
const loading = ref(false)
const error = ref('')
const logs = ref<AdminLogs>({ downloads: [], design: [] })
const filterUser = ref('')
const filterAction = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    logs.value = await adminLogs()
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const users = ref<string[]>([])
const actions = ref<string[]>([])
function deriveFilters() {
  users.value = [...new Set(logs.value.downloads.map(d => d.username).concat(logs.value.design.map(d => d.username)))].sort()
  actions.value = [...new Set(logs.value.downloads.map(d => d.action))].sort()
}

const filteredDownloads = () => logs.value.downloads.filter(d =>
  (!filterUser.value || d.username === filterUser.value) &&
  (!filterAction.value || d.action === filterAction.value)
)
const filteredDesign = () => logs.value.design.filter(d =>
  !filterUser.value || d.username === filterUser.value
)

async function rollbackTo(seq: number, project: string, instruction: string) {
  if (!confirm(`从设计日志第 ${seq} 步重新设计？\n\n该步: ${(instruction || '').slice(0, 60)}\n\n模型将恢复到该步开始前的状态，后续指令基于此状态增量修改。`)) return
  try {
    const r = await designLogRollback(project, seq)
    alert('✅ ' + (r?.message || `已恢复到第 ${seq} 步`))
    await load()
  } catch (e: any) {
    alert('回滚失败: ' + (e?.message || e))
  }
}

onMounted(async () => { await load(); deriveFilters() })
</script>

<template>
  <div class="logs-view">
    <div class="logs-hd">
      <h3>📋 日志查看</h3>
      <span class="logs-sub">仅管理员可见 · 下载追溯 + 设计日志</span>
      <div class="logs-filters">
        <select v-model="filterUser" class="filter-select" @change="deriveFilters">
          <option value="">全部用户</option>
          <option v-for="u in users" :key="u" :value="u">{{ u }}</option>
        </select>
        <select v-if="tab === 'downloads'" v-model="filterAction" class="filter-select">
          <option value="">全部动作</option>
          <option v-for="a in actions" :key="a" :value="a">{{ a }}</option>
        </select>
        <button class="btn-refresh" @click="load">⟳ 刷新</button>
      </div>
      <div class="logs-tabs">
        <button class="tab-btn" :class="{ active: tab === 'downloads' }" @click="tab = 'downloads'">⬇ 下载日志 ({{ logs.downloads.length }})</button>
        <button class="tab-btn" :class="{ active: tab === 'design' }" @click="tab = 'design'">🧩 设计日志 ({{ logs.design.length }})</button>
      </div>
    </div>

    <div v-if="error" class="logs-error">{{ error }}</div>
    <div v-if="loading" class="logs-empty">加载中…</div>

    <div v-else-if="tab === 'downloads'" class="logs-body">
      <table class="logs-table">
        <thead>
          <tr>
            <th>时间</th><th>用户</th><th>项目</th><th>文件</th><th>动作</th><th>大小</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in filteredDownloads()" :key="i">
            <td class="col-time">{{ d.time }}</td>
            <td>{{ d.username }}</td>
            <td class="col-proj" :title="d.project">{{ d.project }}</td>
            <td class="col-file" :title="d.file">{{ d.file }}</td>
            <td><span class="badge" :class="d.action">{{ d.action }}</span></td>
            <td class="col-size">{{ d.size }} B</td>
          </tr>
          <tr v-if="!filteredDownloads().length"><td colspan="6" class="logs-empty">暂无下载记录</td></tr>
        </tbody>
      </table>
    </div>

    <div v-else class="logs-body">
      <table class="logs-table">
        <thead>
          <tr>
            <th>#</th><th>时间</th><th>用户</th><th>项目</th><th>动作</th><th>设计指示</th><th>LLM 回应</th><th>结果目录</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in filteredDesign()" :key="i">
            <td class="col-seq">{{ d.seq }}</td>
            <td class="col-time">{{ d.time }}</td>
            <td>{{ d.username }}</td>
            <td class="col-proj" :title="d.project">{{ d.project }}</td>
            <td><span class="badge action-badge">{{ d.action }}</span></td>
            <td class="col-instruction" :title="d.instruction">{{ d.instruction }}</td>
            <td class="col-llm" :title="d.llm_response">{{ d.llm_response }}</td>
            <td class="col-out" :title="d.output_dir">{{ d.output_dir }}</td>
            <td>
              <button class="btn-rollback" title="从这一步重新设计" @click="rollbackTo(d.seq, d.project, d.instruction)">↩ 重设计</button>
            </td>
          </tr>
          <tr v-if="!filteredDesign().length"><td colspan="9" class="logs-empty">暂无设计日志</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.logs-view{flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;padding:16px 20px;overflow:hidden}
.logs-hd{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.logs-hd h3{font-size:16px;font-weight:700;color:#333;margin:0}
.logs-sub{font-size:11px;color:#999}
.logs-filters{display:flex;gap:8px;margin-left:auto}
.filter-select{border:1px solid #d0d0d4;border-radius:6px;padding:4px 8px;font-size:12px;background:#fff;color:#333}
.btn-refresh{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:4px 12px;font-size:12px;cursor:pointer}
.btn-refresh:hover{background:#4338ca}
.logs-tabs{display:flex;gap:8px;width:100%}
.tab-btn{background:#f3f4f6;border:1px solid #e5e5e5;border-radius:6px;padding:6px 14px;font-size:12px;cursor:pointer;color:#555}
.tab-btn.active{background:#e0e7ff;color:#4f46e5;font-weight:600;border-color:#4f46e5}
.logs-body{flex:1;overflow:auto;border:1px solid #e5e5e5;border-radius:8px}
.logs-table{width:100%;border-collapse:collapse;font-size:12px}
.logs-table th{position:sticky;top:0;background:#f8f8f8;font-size:11px;color:#888;text-align:left;padding:8px 10px;border-bottom:1px solid #e5e5e5;z-index:2}
.logs-table td{padding:6px 10px;border-bottom:1px solid #f0f0f0;vertical-align:top;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logs-table tr:hover td{background:#f5f7ff}
.col-time{white-space:nowrap;color:#666;font-family:monospace;font-size:11px}
.col-proj{max-width:120px}
.col-file{max-width:300px;font-family:monospace;font-size:11px;color:#444}
.col-size{white-space:nowrap;color:#888}
.col-instruction{max-width:220px;color:#333}
.col-llm{max-width:260px;color:#666}
.col-out{max-width:180px;font-family:monospace;font-size:11px;color:#444}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;background:#eef2ff;color:#4f46e5}
.badge.download{background:#ecfdf5;color:#059669}
.badge.view{background:#eff6ff;color:#2563eb}
.action-badge{background:#f3f4f6;color:#555}
.col-seq{width:34px;text-align:center;font-weight:700;color:#4f46e5;font-family:monospace}
.btn-rollback{background:#fff7ed;border:1px solid #fdba74;color:#ea580c;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;white-space:nowrap}
.btn-rollback:hover{background:#ffedd5}
.logs-error{color:#dc2626;font-size:13px;padding:12px}
.logs-empty{color:#aaa;text-align:center;padding:30px 0;font-size:13px}
</style>
