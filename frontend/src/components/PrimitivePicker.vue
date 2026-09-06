<template>
  <div class="prim-picker">
    <div class="prim-hd">
      <span class="prim-title">🧩 图元库</span>
      <span class="prim-sub">点选图元 → 填参数 → 生成</span>
    </div>

    <div v-if="loading" class="prim-loading">加载图元库...</div>
    <div v-else-if="error" class="prim-error">{{ error }}</div>

    <div v-else class="prim-body">
      <!-- 左：图元列表 -->
      <div class="prim-list">
        <div
          v-for="(meta, type) in primitives"
          :key="type"
          class="prim-item"
          :class="{ active: selected === type }"
          @click="selectType(type)"
        >
          <span class="prim-icon">{{ iconFor(type) }}</span>
          <div class="prim-meta">
            <div class="prim-name">{{ nameFor(type) }}</div>
            <div class="prim-desc">{{ meta.description }}</div>
          </div>
        </div>
      </div>

      <!-- 右：参数表单 -->
      <div class="prim-form">
        <template v-if="selected">
          <div class="form-title">{{ nameFor(selected) }}</div>
          <div class="form-row" v-for="(desc, pname) in primitives[selected].params" :key="pname">
            <label>{{ pname }}</label>
            <input
              v-model="formValues[pname]"
              :placeholder="desc"
              type="text"
            />
            <span class="form-desc">{{ shortDesc(desc) }}</span>
          </div>
          <div class="form-actions">
            <button class="prim-btn prim-add" @click="addPart" :disabled="store.busy" title="➕添加零件">➕ 添加零件</button>
            <button class="prim-btn prim-clear" @click="clearForm" title="清空">清空</button>
          </div>
        </template>
        <div v-else class="form-empty">← 选择一个图元开始</div>
      </div>
    </div>

    <div v-if="store.busy" class="prim-busy">⏳ AI 建模中...</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import * as api from '@/api'

const store = useAppStore()
const primitives = ref<Record<string, any>>({})
const loading = ref(true)
const error = ref('')
const selected = ref('')
const formValues = ref<Record<string, string>>({})

// 图元中文名 + 图标
const TYPE_META: Record<string, { name: string; icon: string }> = {
  shell_box: { name: '壳体/箱体', icon: '📦' },
  wedge_box: { name: '楔形箱体', icon: '🔻' },
  u_channel: { name: 'U型槽', icon: '🛤️' },
  u_channel_bellows: { name: 'U型槽+波纹管', icon: '〰️' },
  hinge_connection: { name: '铰链连接', icon: '🔩' },
  bellows_seal: { name: '波纹管密封', icon: '🌀' },
  plate: { name: '平板', icon: '⬜' },
  cylinder: { name: '圆柱', icon: '🥫' },
  sphere: { name: '球体', icon: '⚪' },
  side_shaft: { name: '侧轴', icon: '📌' },
  side_hole: { name: '侧孔', icon: '⭕' },
  extruded_profile: { name: '拉伸轮廓', icon: '📐' },
  revolved_solid: { name: '回转体', icon: '🔆' },
  fillet: { name: '圆角', icon: '◜' },
  pattern: { name: '阵列', icon: '🔁' },
}

function iconFor(type: string): string {
  return TYPE_META[type]?.icon || '🧩'
}
function nameFor(type: string): string {
  return TYPE_META[type]?.name || type
}
function shortDesc(desc: string): string {
  return desc.length > 60 ? desc.slice(0, 60) + '...' : desc
}

function selectType(type: string) {
  selected.value = type
  formValues.value = { name: nameFor(type).toLowerCase().replace(/[^a-z0-9_]/g, '_') }
  // 预填常用参数默认值
  const params = primitives.value[type]?.params || {}
  for (const p of Object.keys(params)) {
    if (p === 'name') continue
    if (p === 'L' || p === 'W' || p === 'H' || p === 't' || p === 'r' || p === 'radius') {
      if (formValues.value[p] === undefined) formValues.value[p] = p === 't' ? '3' : '100'
    }
  }
}

function clearForm() {
  formValues.value = { name: '' }
}

function buildPartMessage(): string {
  const type = selected.value
  const params: Record<string, any> = {}
  const metaParams = primitives.value[type]?.params || {}
  for (const p of Object.keys(metaParams)) {
    const v = formValues.value[p]
    if (v === undefined || v === '') continue
    // 尝试转数字，失败保留字符串
    const num = Number(v)
    params[p] = isNaN(num) ? v : num
  }
  return `请添加一个${nameFor(type)}零件。\n类型: ${type}\n参数: ${JSON.stringify(params)}\n使用 model_add_part 工具创建。`
}

function addPart() {
  if (!selected.value) return
  const msg = buildPartMessage()
  store.send(msg)
}

onMounted(async () => {
  try {
    const data = await api.getPrimitives()
    if (data.error) {
      error.value = data.error
    } else {
      primitives.value = data
    }
  } catch (e: any) {
    error.value = '加载失败: ' + (e?.message || e)
  } finally {
    loading.value = false
  }
})

watch(() => store.busy, (b) => {
  if (!b) clearForm()
})
</script>

<style scoped>
.prim-picker {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  display: flex;
  flex-direction: column;
  max-height: 520px;
  overflow: hidden;
}
.prim-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}
.prim-title { font-weight: 600; color: #334; }
.prim-sub { font-size: 11px; color: #999; }
.prim-loading, .prim-error { padding: 20px; text-align: center; color: #888; font-size: 13px; }
.prim-error { color: #d33; }
.prim-body {
  display: flex;
  min-height: 300px;
}
.prim-list {
  width: 220px;
  border-right: 1px solid #e2e8f0;
  overflow-y: auto;
  flex-shrink: 0;
}
.prim-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
  transition: background .12s;
}
.prim-item:hover { background: #f5f8ff; }
.prim-item.active { background: #e8f0ff; border-left: 3px solid #4a7dff; }
.prim-icon { font-size: 18px; flex-shrink: 0; }
.prim-meta { min-width: 0; }
.prim-name { font-size: 13px; font-weight: 600; color: #334; }
.prim-desc { font-size: 11px; color: #888; margin-top: 2px; line-height: 1.4; }
.prim-form {
  flex: 1;
  padding: 12px 14px;
  overflow-y: auto;
}
.form-title { font-size: 14px; font-weight: 600; color: #111; margin-bottom: 10px; }
.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.form-row label {
  width: 60px;
  font-size: 12px;
  color: #556;
  text-align: right;
  font-family: monospace;
  flex-shrink: 0;
}
.form-row input {
  flex: 1;
  min-width: 120px;
  padding: 5px 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 12px;
  outline: none;
}
.form-row input:focus { border-color: #4a7dff; }
.form-desc { font-size: 10px; color: #aaa; width: 100%; margin-left: 68px; }
.form-actions { display: flex; gap: 8px; margin-top: 12px; }
.prim-btn {
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
}
.prim-add { background: #4a7dff; color: #fff; }
.prim-add:hover { background: #3a6ce0; }
.prim-add:disabled { opacity: .5; cursor: not-allowed; }
.prim-clear { background: #fff; color: #556; border-color: #d1d5db; }
.form-empty { color: #aaa; font-size: 13px; padding: 40px 0; text-align: center; }
.prim-busy { padding: 8px 14px; color: #4a7dff; font-size: 13px; border-top: 1px solid #e2e8f0; background: #f5f8ff; }
</style>
