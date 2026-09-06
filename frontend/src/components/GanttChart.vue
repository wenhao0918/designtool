<script setup lang="ts">
/**
 * GanttChart — 树形甘特图(多级子任务)
 * - 任意层级子任务(递归树)
 * - 有子任务的节点:起止日期自动 = 子任务范围(只读显示)
 * - 叶子任务:日期可编辑
 * - 折叠箭头仅在有子任务时显示
 */
import { ref, computed, watch, onMounted } from 'vue'
import * as api from '@/api'
import type { GanttFileInfo } from '@/api'

export interface GanttTask {
  id: number
  name: string
  start?: string     // 叶子任务起止
  end?: string
  milestone?: boolean
  preds?: number[]
  children?: GanttTask[]
}

const props = defineProps<{ project: string }>()
const emit = defineEmits<{ (e: 'saved-as', name: string): void }>()

const COLORS = ['#4472C4', '#ED7D31', '#70AD47', '#FFC000', '#7F7F7F', '#5B9BD5', '#A5A5A5']

const key = computed(() => `gantt_${props.project || 'default'}`)
const tasks = ref<GanttTask[]>([])
const planName = ref('')  // 计划名称(用于保存/新建/换名)
const showNameDialog = ref(false)  // 新建/换名对话框
const fileInput = ref<HTMLInputElement | null>(null)
const selectedId = ref<number | null>(null)
const hoverId = ref<number | null>(null)
const collapsed = ref<Set<number>>(new Set())
const now = new Date()
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
const DAY = 86400000

// ---- 示例数据(国能项目,三级结构示范) ----
function defaultTasks(): GanttTask[] {
  const BASE = new Date(2026, 7, 17)
  const s = (day: number) => {
    const d = new Date(BASE.getTime() + (day - 1) * DAY)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
  return [
    { id: 1, name: '一、需求分析与设计', children: [
      { id: 11, name: '需求调研与确认', start: s(1), end: s(15) },
      { id: 12, name: '现场踏勘', start: s(5), end: s(20) },
      { id: 13, name: '系统详细设计', start: s(10), end: s(40), preds: [11] },
      { id: 14, name: '硬件方案确认', start: s(15), end: s(30), preds: [11] },
    ]},
    { id: 2, name: '二、供货与硬件部署', children: [
      { id: 21, name: '硬件采购', start: s(25), end: s(40), preds: [14] },
      { id: 22, name: '上架安装与布线', start: s(40), end: s(80), preds: [21], children: [
        { id: 221, name: '边缘服务器上架', start: s(40), end: s(60) },
        { id: 222, name: '前端感知设备安装', start: s(55), end: s(75) },
        { id: 223, name: '网络布线', start: s(60), end: s(80), preds: [221] },
      ]},
      { id: 23, name: '环境验证', start: s(75), end: s(90), preds: [22] },
    ]},
    { id: 3, name: '三、软件开发与部署', children: [
      { id: 31, name: '统一支撑平台开发', start: s(40), end: s(120), preds: [13] },
      { id: 32, name: 'AI算法部署调优', start: s(55), end: s(130), preds: [31] },
      { id: 33, name: '业务应用系统开发', start: s(60), end: s(130), preds: [31] },
      { id: 34, name: '接口开发(MES/监控)', start: s(55), end: s(130), preds: [13] },
    ]},
    { id: 4, name: '四、集成测试与培训', children: [
      { id: 41, name: '系统集成测试', start: s(125), end: s(155), preds: [31, 32, 33] },
      { id: 42, name: '安全测试', start: s(145), end: s(160), preds: [41] },
      { id: 43, name: '用户培训', start: s(130), end: s(160), preds: [31] },
    ]},
    { id: 5, name: '五、验收交付', children: [
      { id: 51, name: '初验', start: s(160), end: s(180), preds: [41, 42, 43], milestone: true },
      { id: 52, name: '试运行(6个月)', start: s(180), end: s(360), preds: [51] },
      { id: 53, name: '终验', start: s(360), end: s(365), preds: [52], milestone: true },
    ]},
    { id: 6, name: '六、质保服务', children: [
      { id: 61, name: '质保服务(1年)', start: s(365), end: s(730), preds: [53] },
    ]},
  ]
}

// ---- 持久化:后端优先,localStorage 兜底 ----
const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const backendSaved = ref(false)  // 是否已保存到后端

async function load() {
  // 1. 后端加载(若项目存在且已有数据)
  if (props.project) {
    try {
      const r = await api.getGantt(props.project)
      if (r.content && r.content.trim()) {
        tasks.value = JSON.parse(r.content)
        backendSaved.value = true
        return
      }
    } catch (e) {
      console.warn('gantt load backend failed, fallback to local', e)
    }
  }
  // 2. localStorage 兜底
  try {
    const raw = localStorage.getItem(key.value)
    tasks.value = raw ? JSON.parse(raw) : defaultTasks()
  } catch { tasks.value = defaultTasks() }
}

// 本地自动保存(编辑即时存 localStorage,不阻塞)
function saveLocal() { localStorage.setItem(key.value, JSON.stringify(tasks.value)) }

// 保存到后端(显式按钮 + 自动)
async function saveToBackend() {
  if (!props.project) { saveStatus.value = 'error'; return }
  saveStatus.value = 'saving'
  try {
    await api.saveGantt(props.project, JSON.stringify(tasks.value))
    backendSaved.value = true
    saveStatus.value = 'saved'
    setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = 'idle' }, 2000)
  } catch (e) {
    console.error('gantt save failed', e)
    saveStatus.value = 'error'
  }
}

// 所有编辑操作:本地即时存;后端保存由显式按钮触发(或切换项目前)
function save() {
  saveLocal()
}

watch(key, () => load(), { immediate: true })
onMounted(load)

// ---- 递归工具 ----
function findParent(list: GanttTask[], id: number): GanttTask | null {
  for (const t of list) {
    if (t.children && t.children.some(c => c.id === id)) return t
    if (t.children) { const f = findParent(t.children, id); if (f) return f }
  }
  return null
}
function removeById(list: GanttTask[], id: number): boolean {
  for (let i = 0; i < list.length; i++) {
    if (list[i].id === id) { list.splice(i, 1); return true }
    if (list[i].children && removeById(list[i].children!, id)) return true
  }
  return false
}

// 有效起止:有子任务 → 子任务范围(递归);叶子 → 自身
function effStart(t: GanttTask): string {
  if (t.children && t.children.length) {
    let min = '9999-12-31'
    for (const c of t.children) { const cs = effStart(c); if (cs < min) min = cs }
    return min
  }
  return t.start || today
}
function effEnd(t: GanttTask): string {
  if (t.children && t.children.length) {
    let max = '0000-01-01'
    for (const c of t.children) { const ce = effEnd(c); if (ce > max) max = ce }
    return max
  }
  return t.end || today
}
const hasChildren = (t: GanttTask) => !!(t.children && t.children.length)

// ---- 扁平化行(带层级,递归展开) ----
interface Row { task: GanttTask; level: number; parentId: number | null }
const rows = computed<Row[]>(() => {
  const out: Row[] = []
  const walk = (list: GanttTask[], level: number, parentId: number | null) => {
    for (const t of list) {
      out.push({ task: t, level, parentId })
      if (hasChildren(t) && !collapsed.value.has(t.id)) walk(t.children!, level + 1, t.id)
    }
  }
  walk(tasks.value, 0, null)
  return out
})

// ---- 甘特图计算 ----
const minDate = computed(() => rows.value.length ? rows.value.reduce((a, r) => effStart(r.task) < a ? effStart(r.task) : a, effStart(rows.value[0].task)) : today)
const maxDate = computed(() => rows.value.length ? rows.value.reduce((a, r) => effEnd(r.task) > a ? effEnd(r.task) : a, effEnd(rows.value[0].task)) : today)
function parse(d: string): number { return new Date(d).getTime() }
function fmt(ms: number): string {
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function addDays(ms: number, n: number): number { return ms + n * DAY }
const totalDays = computed(() => Math.max(1, Math.round((parse(maxDate.value) - parse(minDate.value)) / DAY) + 20))
const startMs = computed(() => parse(minDate.value) - 10 * DAY)
function leftPct(d: string): number { return ((parse(d) - startMs.value) / DAY / totalDays.value) * 100 }
function widthPct(t: GanttTask): number {
  const w = Math.max(1, Math.round((parse(effEnd(t)) - parse(effStart(t))) / DAY) + 1)
  return (w / totalDays.value) * 100
}
const monthTicks = computed(() => {
  const ticks: { label: string; left: number }[] = []
  for (let i = 0; i < totalDays.value; i += 30) {
    const d = new Date(addDays(startMs.value, i))
    ticks.push({ label: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, left: (i / totalDays.value) * 100 })
  }
  return ticks
})
function taskColor(t: GanttTask): string {
  const parent = findParent(tasks.value, t.id)
  let idx = 0
  if (parent) {
    const pp = findParent(tasks.value, parent.id)
    if (pp) idx = pp.children!.findIndex(c => c.id === parent.id)
    else idx = tasks.value.findIndex(p => p.id === parent.id)
  }
  return COLORS[(Math.max(0, idx) % COLORS.length)]
}

// ---- 操作 ----
let nextId = 10000
function addRoot() {
  tasks.value.push({ id: nextId++, name: '新分组', children: [] })
  save()
}
function addChild(t: GanttTask) {
  if (!t.children) t.children = []
  t.children.push({ id: nextId++, name: '新任务', start: effStart(t), end: effEnd(t) })
  save()
}
function removeTask(t: GanttTask) {
  const parent = findParent(tasks.value, t.id)
  if (parent && parent.children) removeById(parent.children, t.id)
  else removeById(tasks.value, t.id)
  save()
}
function toggleMilestone(t: GanttTask) { t.milestone = !t.milestone; save() }
function nudge(t: GanttTask, delta: number, field: 'start' | 'end') {
  if (hasChildren(t)) return
  if (field === 'start') {
    t.start = fmt(addDays(parse(effStart(t)), delta))
    if (parse(t.end || '') < parse(t.start)) t.end = t.start
  } else {
    t.end = fmt(addDays(parse(effEnd(t)), delta))
    if (parse(t.end) < parse(t.start || '')) t.start = t.end
  }
  save()
}
function toggleCollapse(id: number) {
  const s = new Set(collapsed.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  collapsed.value = s
}

// ---- 下载 JSON 备份 ----
function downloadJson() {
  const blob = new Blob([JSON.stringify(tasks.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `甘特图_${props.project || 'default'}_${today}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// ---- 导出 PNG(用 SVG 转 canvas 画甘特图) ----
function exportPng() {
  const W = 1400
  const H = Math.max(400, 90 + rows.value.length * 30 + 40)
  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H)
  ctx.font = 'bold 22px sans-serif'; ctx.fillStyle = '#333'
  ctx.fillText('📊 项目甘特图 - ' + (props.project || '默认项目'), 30, 40)

  // 时间轴范围
  const tMin = parse(minDate.value), tMax = parse(maxDate.value)
  const span = Math.max(1, (tMax - tMin) / DAY)
  const gx0 = 320, gx1 = W - 40, gw = gx1 - gx0

  // 表头
  ctx.font = '13px sans-serif'; ctx.fillStyle = '#666'
  const months: { label: string; x: number }[] = []
  for (let m = new Date(tMin); m <= new Date(tMax); m.setMonth(m.getMonth() + 1)) {
    const x = gx0 + ((m.getTime() - tMin) / DAY / span) * gw
    months.push({ label: `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}`, x })
  }
  months.forEach((m, i) => { if (i % 2 === 0) ctx.fillText(m.label, m.x, 70) })

  // 每行任务
  let y = 90
  const rowH = 30
  for (const row of rows.value) {
    const t = row.task
    const s = parse(effStart(t)), e = parse(effEnd(t))
    const x = gx0 + ((s - tMin) / DAY / span) * gw
    const w = Math.max(4, ((e - s) / DAY / span) * gw)
    // 行背景
    ctx.fillStyle = hasChildren(t) ? '#eef2f8' : (row.level % 2 ? '#fafafa' : '#fff')
    ctx.fillRect(gx0 - 290, y, gw + 290, rowH - 4)
    // 任务名(缩进)
    ctx.font = '13px sans-serif'
    ctx.fillStyle = '#222'
    ctx.fillText(t.name, 30 + row.level * 22, y + 19)
    // 甘特条(最小宽度保证可见)
    ctx.fillStyle = hasChildren(t) ? '#2E75B6' : taskColor(t)
    if (t.milestone) { ctx.fillStyle = '#C00000' }
    const barW = Math.max(w, t.milestone ? 10 : 24)
    ctx.fillRect(x, y + 8, barW, 14)
    // 起止日期(画在条正上方,深灰,不与条重叠)
    const dateStr = `${effStart(t).slice(5)} ~ ${effEnd(t).slice(5)}`
    ctx.font = 'bold 11px sans-serif'
    ctx.fillStyle = '#333'
    ctx.fillText(dateStr, x, y + 6)
    y += rowH
  }
  const url = canvas.toDataURL('image/png')
  const a = document.createElement('a')
  a.href = url
  a.download = `甘特图_${props.project || 'default'}_${today}.png`
  a.click()
}

// ---- 导出 Excel(CSV with BOM,Excel 可开) ----
function exportExcel() {
  const lines: string[] = ['序号,任务,层级,开始日期,结束日期,里程碑,前置']
  const walk = (list: GanttTask[], level: number) => {
    list.forEach((t, i) => {
      const pre = t.preds ? t.preds.join(';') : ''
      lines.push(`${i + 1},"${t.name.replace(/"/g, '""')}",${level},${effStart(t)},${effEnd(t)},${t.milestone ? '是' : ''},${pre}`)
      if (t.children) walk(t.children, level + 1)
    })
  }
  walk(tasks.value, 0)
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `甘特图_${props.project || 'default'}_${today}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ---- 从服务器打开(列出服务器上所有已保存的甘特图,点选加载) ----
const serverDialog = ref(false)
const serverFiles = ref<GanttFileInfo[]>([])
const serverLoading = ref(false)

async function openServerDialog() {
  serverDialog.value = true
  serverLoading.value = true
  try {
    serverFiles.value = await api.listGantt()
  } catch (e) {
    console.error('gantt server list failed', e)
    serverFiles.value = []
  } finally {
    serverLoading.value = false
  }
}

async function pickServerFile(f: GanttFileInfo) {
  serverDialog.value = false
  try {
    const r = await api.getGantt(f.project_id)
    if (!r.content || !r.content.trim()) { alert('服务器上该文件内容为空'); return }
    const data = JSON.parse(r.content)
    if (!Array.isArray(data)) throw new Error('not array')
    tasks.value = data
    backendSaved.value = true
    // 打开的是别的项目 → 切换当前项目,后续保存写回原项目,不会串数据
    if (f.project_id !== props.project) {
      emit('saved-as', f.project_id)
    }
  } catch (err) {
    alert('服务器文件格式错误,无法打开')
  }
}

// ---- 打开文件(从 JSON 上传恢复) ----
function openFile() {
  fileInput.value?.click()
}
function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(String(reader.result))
      if (!Array.isArray(data)) throw new Error('不是任务数组')
      tasks.value = data
      saveLocal()
      saveToBackend()
      alert(`已从「${file.name}」加载 ${data.length} 个任务`)
    } catch (err) {
      alert('文件格式错误,请选择本工具导出的 JSON 文件')
    }
  }
  reader.readAsText(file)
  input.value = ''
}

// ---- 新建计划(重置为示例或空白) / 换名保存 ----
async function newPlan() {
  if (!confirm('新建计划将用空白/示例替换当前内容,未保存的后端数据会丢失。确定?')) return
  tasks.value = defaultTasks()
  saveLocal()
  await saveToBackend()
}
async function renamePlan() {
  showNameDialog.value = true
  planName.value = props.project || ''
}
async function doRename() {
  const name = planName.value.trim()
  if (!name) return
  // 换名 = 创建新项目(拿 project_id) → 保存数据到新项目 → 刷新并切换
  const r = await api.createProject(name, '甘特图计划')
  const newId = r.project_id || name
  await api.saveGantt(newId, JSON.stringify(tasks.value))
  showNameDialog.value = false
  emit('saved-as', newId)
}
</script>

<template>
  <div class="gantt-wrap">
    <div class="gantt-bar">
      <span class="gantt-title">📊 项目甘特图</span>
      <span class="gantt-sub">{{ props.project || '默认项目' }}</span>
      <span class="save-status" :class="saveStatus">
        {{ saveStatus === 'saving' ? '保存中…' : saveStatus === 'saved' ? '✓ 已保存到后端' : saveStatus === 'error' ? '✗ 保存失败' : (backendSaved ? '已同步' : '本地') }}
      </span>
      <button class="btn-add" @click="saveToBackend" :disabled="saveStatus === 'saving'" title="保存">💾 保存到后端</button>
      <button class="btn-sec" @click="newPlan" title="新建计划">+ 新建</button>
      <button class="btn-sec" @click="renamePlan" title="手绘草图">✏️ 换名保存</button>
      <button class="btn-sec" @click="openServerDialog" title="从服务器打开">☁ 从服务器打开</button>
      <button class="btn-sec" @click="openFile" title="从本地打开">📂 打开文件</button>
      <input ref="fileInput" type="file" accept=".json,application/json" style="display:none" @change="onFilePicked" />
      <button class="btn-sec" @click="downloadJson" title="下载文件">⬇ 下载</button>
      <button class="btn-sec" @click="exportPng" title="导出 PNG">🖼 导出图像</button>
      <button class="btn-sec" @click="exportExcel" title="导出 CSV">📊 导出Excel</button>
    </div>

    <!-- 换名对话框 -->
    <div v-if="showNameDialog" class="dialog-mask" @click.self="showNameDialog = false">
      <div class="dialog">
        <h3>保存为新项目</h3>
        <input v-model="planName" class="name-input dialog-input" placeholder="新计划名称" @keyup.enter="doRename" />
        <div class="dialog-btns">
          <button class="btn-sec" @click="showNameDialog = false" title="取消">取消</button>
          <button class="btn-add" @click="doRename" title="保存">确定保存</button>
        </div>
      </div>
    </div>

    <!-- 从服务器打开对话框 -->
    <div v-if="serverDialog" class="dialog-mask" @click.self="serverDialog = false">
      <div class="dialog server-dialog">
        <h3>☁ 从服务器打开</h3>
        <div class="server-list">
          <div v-if="serverLoading" class="server-empty">加载中…</div>
          <template v-else>
            <div v-for="f in serverFiles" :key="f.project_id" class="server-item" @click="pickServerFile(f)">
              <span class="server-name">{{ f.name }}</span>
              <span class="server-meta">{{ f.task_count }} 个任务 · {{ f.updated }}</span>
            </div>
            <div v-if="!serverFiles.length" class="server-empty">服务器上暂无甘特图文件</div>
          </template>
        </div>
        <div class="dialog-btns">
          <button class="btn-sec" @click="serverDialog = false" title="取消">取消</button>
        </div>
      </div>
    </div>

    <div class="gantt-body">
      <table class="task-table">
        <thead>
          <tr>
            <th class="th-num" style="width:34px">#</th>
            <th style="width:240px">任务</th>
            <th style="width:180px">开始</th>
            <th style="width:180px">结束</th>
            <th class="th-chart" style="width:auto;min-width:360px">
              <div class="chart-header">
                <span v-for="(m, i) in monthTicks" :key="i" class="month-label" :style="{ left: m.left + '%' }">{{ m.label }}</span>
              </div>
            </th>
            <th class="th-ops" style="width:64px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="row.task.id"
            :class="{ selected: selectedId === row.task.id, parent: hasChildren(row.task) }"
            @click="selectedId = row.task.id"
            @mouseenter="hoverId = row.task.id" @mouseleave="hoverId = null">
            <td class="td-num">{{ index + 1 }}</td>
            <td class="cell-name">
              <div class="cell-flex" :style="{ paddingLeft: (row.level * 22) + 'px' }">
                <span v-if="hasChildren(row.task)" class="fold-btn" @click.stop="toggleCollapse(row.task.id)">{{ collapsed.has(row.task.id) ? '▶' : '▼' }}</span>
                <span v-else class="fold-placeholder"></span>
                <span class="milestone-dot" v-if="row.task.milestone" title="里程碑">◆</span>
                <input v-model="row.task.name" @change="save" class="name-input" />
                <button class="mini-btn add-child" title="添加子任务" @click.stop="addChild(row.task)">+</button>
              </div>
            </td>
            <td class="cell-date">
              <div class="cell-flex">
                <button v-if="!hasChildren(row.task)" class="mini-btn nudge-btn" title="提前1天" @click.stop="nudge(row.task, -1, 'start')">−</button>
                <input v-if="!hasChildren(row.task)" v-model="row.task.start" type="date" @change="save" class="date-input" />
                <span v-else class="derived-date">{{ effStart(row.task) }}</span>
                <button v-if="!hasChildren(row.task)" class="mini-btn nudge-btn" title="延后1天" @click.stop="nudge(row.task, 1, 'start')">+</button>
              </div>
            </td>
            <td class="cell-date">
              <div class="cell-flex">
                <button v-if="!hasChildren(row.task)" class="mini-btn nudge-btn" title="提前1天" @click.stop="nudge(row.task, -1, 'end')">−</button>
                <input v-if="!hasChildren(row.task)" v-model="row.task.end" type="date" @change="save" class="date-input" />
                <span v-else class="derived-date">{{ effEnd(row.task) }}</span>
                <button v-if="!hasChildren(row.task)" class="mini-btn nudge-btn" title="延后1天" @click.stop="nudge(row.task, 1, 'end')">+</button>
              </div>
            </td>
            <td class="td-chart" @click.stop="selectedId = row.task.id">
              <div class="gantt-bar-track">
                <div class="gantt-bar" :class="{ milestone: row.task.milestone, parent: hasChildren(row.task) }"
                  :style="{ left: leftPct(effStart(row.task)) + '%', width: widthPct(row.task) + '%', background: hasChildren(row.task) ? '#2E75B6' : taskColor(row.task) }"
                  :title="`${row.task.name}: ${effStart(row.task)} ~ ${effEnd(row.task)}`">
                  <span class="bar-label" v-if="widthPct(row.task) > 8">{{ row.task.name }}</span>
                </div>
              </div>
            </td>
            <td class="td-ops">
              <button v-if="!hasChildren(row.task)" class="mini-btn mile-btn" :class="{ on: row.task.milestone }" title="里程碑" @click.stop="toggleMilestone(row.task)">◆</button>
              <button class="mini-btn del-btn" title="删除" @click.stop="removeTask(row.task)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="legend">
      <span class="legend-item"><i class="legend-color" style="background:#2E75B6"></i>分组(日期自动=子任务范围)</span>
      <span class="legend-item"><i class="legend-color" style="background:#4472C4"></i>任务</span>
      <span class="legend-item"><i class="legend-color milestone-legend">◆</i>里程碑</span>
    </div>
  </div>
</template>

<style scoped>
.gantt-wrap{flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;font-size:13px}
.gantt-bar{display:flex;align-items:center;gap:12px;padding:8px 14px;border-bottom:1px solid #e5e5e5;flex-shrink:0;position:relative;z-index:10}
.gantt-title{font-size:15px;font-weight:700;color:#333}
.gantt-sub{font-size:11px;color:#999}
.btn-add{margin-left:auto;background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:12px;cursor:pointer;position:relative;z-index:11}
.btn-add:hover{background:#4338ca}
.btn-add:disabled{opacity:.5;cursor:not-allowed}
.btn-sec{background:#fff;color:#555;border:1px solid #d0d0d4;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer}
.btn-sec:hover{background:#f0f0f4}
.save-status{font-size:11px;color:#999}
.save-status.saving{color:#d97706}
.save-status.saved{color:#16a34a}
.save-status.error{color:#dc2626}

.dialog-mask{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:100;display:flex;align-items:center;justify-content:center}
.dialog{background:#fff;border-radius:10px;padding:20px 24px;min-width:320px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
.server-dialog{min-width:420px}
.server-list{max-height:320px;overflow-y:auto;margin-bottom:14px}
.server-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 12px;border:1px solid #e5e5e5;border-radius:6px;margin-bottom:6px;cursor:pointer}
.server-item:hover{background:#f5f7ff;border-color:#4f46e5}
.server-name{font-size:13px;color:#333;font-weight:600}
.server-meta{font-size:11px;color:#999;flex-shrink:0}
.server-empty{font-size:12px;color:#aaa;text-align:center;padding:20px 0}
.dialog h3{margin:0 0 12px;font-size:15px;color:#333}
.dialog-input{border:1px solid #d0d0d4;border-radius:6px;padding:7px 10px;font-size:13px;width:100%;margin-bottom:14px}
.dialog-btns{display:flex;justify-content:flex-end;gap:8px}
.gantt-tip{font-size:10px;color:#aaa}

.gantt-body{flex:1;min-height:0;overflow:auto}
.task-table{width:100%;border-collapse:collapse;table-layout:fixed}
.task-table th{background:#f8f8f8;font-size:11px;color:#888;text-align:left;padding:6px 8px;position:sticky;top:0;z-index:2}
.task-table td{padding:3px 6px;border-bottom:1px solid #f0f0f0;font-size:12px;vertical-align:middle}
.task-table tr.selected td{background:#eef2ff}
.task-table tr:hover td{background:#f5f7ff}
.task-table tr.parent td{background:#f3f6fb}
.task-table tr.parent.selected td{background:#e0e9f5}

.th-num{width:34px;text-align:center}
.td-num{width:34px;text-align:center;color:#aaa;font-size:11px}
.th-chart{min-width:360px;position:relative;padding:0 !important}
.chart-header{position:relative;height:24px;background:repeating-linear-gradient(90deg,#fafafa 0 39px,#f0f0f0 39px 40px)}
.month-label{position:absolute;top:4px;font-size:9px;color:#999;transform:translateX(-50%);pointer-events:none;white-space:nowrap}
.td-chart{position:relative;padding:0 4px !important;width:auto}
.cell-name{width:240px}
.cell-date{width:180px}
.cell-flex{display:flex;align-items:center;gap:2px;white-space:nowrap;overflow:hidden;height:100%}
.cell-flex .mini-btn{flex-shrink:0}
.cell-flex .date-input{flex-shrink:0;width:100px}
.td-ops{width:64px;text-align:center}
.derived-date{font-size:11px;color:#888;background:#f0f2f5;border-radius:4px;padding:2px 6px;width:100px;text-align:center;flex-shrink:0}

.fold-btn{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;font-size:9px;cursor:pointer;color:#666;background:#e8e8ea;border-radius:3px;flex-shrink:0}
.fold-btn:hover{background:#d0d0d4}
.fold-placeholder{width:16px;flex-shrink:0}
.add-child{color:#4f46e5}

.gantt-bar-track{position:relative;height:26px;background:repeating-linear-gradient(90deg,#fafafa 0 39px,#f0f0f0 39px 40px);border-radius:3px;overflow:hidden}
.gantt-bar{position:absolute;top:4px;height:18px;border-radius:4px;min-width:10px;box-shadow:0 1px 2px rgba(0,0,0,.15);cursor:pointer}
.gantt-bar.parent{height:14px;top:6px;opacity:.75}
.gantt-bar.milestone{background:#C00000 !important;width:14px !important;border-radius:2px}
.gantt-bar:hover{filter:brightness(1.1)}
.bar-label{position:absolute;left:6px;top:2px;color:#fff;font-size:10px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:calc(100% - 8px)}

.name-input{border:none;background:transparent;font-size:12px;width:100%;outline:none;min-width:0;flex:1}
.name-input:focus{border-bottom:1px solid #4f46e5}
.date-input{border:1px solid #e5e5e5;border-radius:4px;font-size:11px;padding:2px 4px;background:#fff}
.mini-btn{border:1px solid #e0e0e0;background:#fff;border-radius:4px;font-size:10px;cursor:pointer;padding:1px 5px;color:#555}
.mini-btn:hover{background:#f0f0f0}
.nudge-btn{width:20px;padding:1px 0;text-align:center;font-size:11px;line-height:1}
.mile-btn.on{background:#fee2e2;color:#C00000;border-color:#fca5a5}
.del-btn:hover{background:#fee2e2;color:#C00000}

.legend{display:flex;align-items:center;gap:14px;padding:6px 14px;border-top:1px solid #e5e5e5;flex-shrink:0;flex-wrap:wrap}
.legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:#666}
.legend-color{width:12px;height:12px;border-radius:3px;display:inline-block}
.milestone-legend{background:none;color:#C00000;font-size:12px;text-align:center}
</style>
