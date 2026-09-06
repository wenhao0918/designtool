<script setup lang="ts">
/**
 * MaterialQuery — 标准件/非标件查询工具
 * 数据源:remote-server mn-material 服务(通过 Anvil /api/material/* 代理)
 * 功能:分类树浏览 + 关键词/分类/品牌搜索 + 结果列表 + 详情查看
 */
import { ref, computed, onMounted } from 'vue'
import * as api from '@/api'

interface Category { id: number; parentId: number; name: string; level: number; sort?: number; specSchema?: string | null }
interface PartRow {
  id: number
  partCode: string
  name: string
  brand?: string
  model?: string
  categoryId?: number
  specs?: string
  material?: string
  supplier?: string
  referencePrice?: number
  unit?: string
  description?: string
  tags?: string
  paramSchema?: string
  defaultParams?: string
}

const tab = ref<'standard' | 'nonstandard' | 'industry' | 'enterprise'>('standard')
// 页签 → 后端 collection 映射
const TAB_COLLECTION: Record<string, 'standardPart' | 'nonstandardPart' | 'industryPart' | 'enterprisePart'> = {
  standard: 'standardPart',
  nonstandard: 'nonstandardPart',
  industry: 'industryPart',
  enterprise: 'enterprisePart',
}
const TAB_LABEL: Record<string, string> = {
  standard: '标准件', nonstandard: '非标件', industry: '行业件', enterprise: '企业自有件',
}
const cats = ref<Category[]>([])
const catTree = computed(() => {
  // 构建树:level1 根 + level2 子
  const roots = cats.value.filter(c => c.level === 1)
  return roots.map(r => ({ ...r, children: cats.value.filter(c => c.parentId === r.id) }))
})
const selCat = ref<number | null>(null)
const keyword = ref('')
const brand = ref('')
const rows = ref<PartRow[]>([])
const total = ref(0)
const loading = ref(false)
const detail = ref<PartRow | null>(null)
const page = ref(1)
const PAGE_SIZE = 50

async function loadCats() {
  try {
    const r = await api.materialList('partCategory', { pageSize: 100 })
    cats.value = r.rows || []
  } catch (e) {
    console.error('loadCats failed', e)
  }
}

async function search(pageNum = 1) {
  loading.value = true
  page.value = pageNum
  try {
    const coll = TAB_COLLECTION[tab.value]
    const r = await api.materialList(coll, {
      pageNum, pageSize: PAGE_SIZE,
      name: keyword.value || undefined,
      categoryId: selCat.value || undefined,
      brand: brand.value || undefined,
    })
    rows.value = r.rows || []
    total.value = r.total || 0
  } catch (e) {
    console.error('search failed', e)
    rows.value = []; total.value = 0
  } finally {
    loading.value = false
  }
}

function selectCat(id: number) {
  selCat.value = selCat.value === id ? null : id
  keyword.value = ''  // 切分类时清空关键词,避免组合过滤困惑
  search(1)
}

function switchTab(t: 'standard' | 'nonstandard' | 'industry' | 'enterprise') {
  tab.value = t
  selCat.value = null
  keyword.value = ''
  search(1)
}

function viewDetail(row: PartRow) {
  detail.value = row
}

function parseSpecs(s?: string): Record<string, any> | null {
  if (!s) return null
  try { return JSON.parse(s) } catch { return null }
}

onMounted(() => { loadCats(); search(1) })
</script>

<template>
  <div class="mat-wrap">
    <!-- 顶部:页签 + 搜索 -->
    <div class="mat-top">
      <div class="mat-tabs">
        <span v-for="(label, key) in TAB_LABEL" :key="key" class="mat-tab" :class="{ on: tab === key }" @click="switchTab(key as any)">{{ label }}</span>
      </div>
      <input v-model="keyword" class="mat-search" placeholder="搜索名称 / 型号…" @keyup.enter="search(1)" />
      <input v-model="brand" class="mat-search mat-brand" placeholder="品牌(可选)" @keyup.enter="search(1)" />
      <button class="mat-btn" @click="search(1)" title="🔍查询">🔍 查询</button>
      <span class="mat-total">共 {{ total }} 条</span>
    </div>

    <div class="mat-body">
      <!-- 左:分类树 -->
      <div class="mat-cats">
        <div class="mat-cats-title">📁 分类</div>
        <div v-for="root in catTree" :key="root.id" class="cat-root">
          <div class="cat-item" :class="{ on: selCat === root.id }" @click="selectCat(root.id)">
            <span class="cat-arrow">▾</span>{{ root.name }}
          </div>
          <div v-for="child in root.children" :key="child.id"
            class="cat-item cat-child" :class="{ on: selCat === child.id }"
            @click="selectCat(child.id)">
            {{ child.name }}
          </div>
        </div>
      </div>

      <!-- 右:结果列表 -->
      <div class="mat-results">
        <div v-if="loading" class="mat-empty">加载中…</div>
        <div v-else-if="rows.length === 0" class="mat-empty">无结果</div>
        <table v-else class="mat-table">
          <thead>
            <tr><th>编号</th><th>名称</th><th>品牌</th><th>型号</th><th>参考价</th><th>单位</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id" @click="viewDetail(r)">
              <td class="mat-code">{{ r.partCode }}</td>
              <td class="mat-name">{{ r.name }}</td>
              <td>{{ r.brand || '-' }}</td>
              <td>{{ r.model || '-' }}</td>
              <td>{{ r.referencePrice != null ? '¥' + r.referencePrice : '-' }}</td>
              <td>{{ r.unit || '-' }}</td>
              <td><button class="mat-btn-sm" @click.stop="viewDetail(r)" title="详情">详情</button></td>
            </tr>
          </tbody>
        </table>
        <!-- 分页 -->
        <div v-if="total > PAGE_SIZE" class="mat-pager">
          <button class="mat-btn-sm" title="‹上一页" :disabled="page <= 1" @click="search(page - 1)">‹ 上一页</button>
          <span>第 {{ page }} 页 / {{ Math.ceil(total / PAGE_SIZE) }} 页</span>
          <button class="mat-btn-sm" title="下一页›" :disabled="page >= Math.ceil(total / PAGE_SIZE)" @click="search(page + 1)">下一页 ›</button>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detail" class="mat-mask" @click.self="detail = null">
      <div class="mat-dialog">
        <div class="mat-dlg-head">
          <h3>{{ detail.name }}</h3>
          <button class="mat-btn-sm" @click="detail = null" title="✕">✕</button>
        </div>
        <div class="mat-dlg-body">
          <table class="mat-detail-table">
            <tr><td>编号</td><td>{{ detail.partCode }}</td></tr>
            <tr><td>品牌</td><td>{{ detail.brand || '-' }}</td></tr>
            <tr><td>型号</td><td>{{ detail.model || '-' }}</td></tr>
            <tr><td>供应商</td><td>{{ detail.supplier || '-' }}</td></tr>
            <tr><td>参考价</td><td>{{ detail.referencePrice != null ? '¥' + detail.referencePrice : '-' }} {{ detail.unit || '' }}</td></tr>
            <tr><td>材质</td><td>{{ detail.material || '-' }}</td></tr>
            <tr v-if="detail.tags"><td>标签</td><td>{{ detail.tags }}</td></tr>
            <tr v-if="detail.description"><td>描述</td><td>{{ detail.description }}</td></tr>
          </table>
          <div v-if="parseSpecs(detail.specs)" class="mat-specs">
            <div class="mat-specs-title">规格参数</div>
            <div class="mat-specs-grid">
              <span v-for="(v, k) in parseSpecs(detail.specs)" :key="k" class="mat-spec">
                <b>{{ k }}</b>: {{ v }}
              </span>
            </div>
          </div>
          <div v-if="parseSpecs(detail.paramSchema)" class="mat-specs">
            <div class="mat-specs-title">参数模板</div>
            <pre class="mat-specs-pre">{{ JSON.stringify(parseSpecs(detail.paramSchema), null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mat-wrap{flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;font-size:13px}
.mat-top{display:flex;align-items:center;gap:8px;padding:8px 14px;border-bottom:1px solid #e5e5e5;flex-shrink:0;flex-wrap:wrap}
.mat-tabs{display:flex;gap:4px}
.mat-tab{padding:4px 14px;border-radius:6px;cursor:pointer;font-size:13px;color:#555;background:#f0f0f4}
.mat-tab.on{background:#4f46e5;color:#fff;font-weight:600}
.mat-search{border:1px solid #d0d0d4;border-radius:6px;padding:5px 10px;font-size:13px;width:220px}
.mat-brand{width:120px}
.mat-btn{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:5px 16px;font-size:13px;cursor:pointer}
.mat-btn:hover{background:#4338ca}
.mat-total{font-size:12px;color:#888;margin-left:auto}

.mat-body{flex:1;display:flex;min-height:0}
.mat-cats{width:220px;border-right:1px solid #e5e5e5;overflow-y:auto;padding:8px 6px;flex-shrink:0}
.mat-cats-title{font-size:12px;color:#888;padding:4px 8px}
.cat-root{margin-bottom:2px}
.cat-item{padding:5px 10px;border-radius:5px;cursor:pointer;font-size:13px;color:#333}
.cat-item:hover{background:#f0f0f4}
.cat-item.on{background:#e0e7ff;color:#4f46e5;font-weight:600}
.cat-child{padding-left:28px;font-size:12px;color:#555}
.cat-arrow{font-size:10px;margin-right:4px;color:#999}

.mat-results{flex:1;overflow-y:auto;padding:8px}
.mat-empty{padding:40px;text-align:center;color:#999}
.mat-table{width:100%;border-collapse:collapse}
.mat-table th{background:#f8f8f8;font-size:11px;color:#888;text-align:left;padding:6px 8px;position:sticky;top:0}
.mat-table td{padding:6px 8px;border-bottom:1px solid #f0f0f0;font-size:12px}
.mat-table tr{cursor:pointer}
.mat-table tr:hover td{background:#f5f7ff}
.mat-code{color:#888;font-size:11px;white-space:nowrap}
.mat-name{font-weight:500}
.mat-btn-sm{border:1px solid #d0d0d4;background:#fff;border-radius:4px;font-size:11px;padding:2px 8px;cursor:pointer;color:#555}
.mat-btn-sm:hover{background:#f0f0f4}
.mat-btn-sm:disabled{opacity:.4;cursor:not-allowed}
.mat-pager{display:flex;align-items:center;gap:12px;justify-content:center;padding:10px;font-size:12px;color:#666}

.mat-mask{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:100;display:flex;align-items:center;justify-content:center}
.mat-dialog{background:#fff;border-radius:10px;width:520px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 10px 30px rgba(0,0,0,.2)}
.mat-dlg-head{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e5e5}
.mat-dlg-head h3{margin:0;font-size:15px}
.mat-dlg-body{padding:14px 18px;overflow-y:auto}
.mat-detail-table{width:100%;border-collapse:collapse}
.mat-detail-table td{padding:5px 8px;font-size:13px;border-bottom:1px solid #f5f5f5}
.mat-detail-table td:first-child{color:#888;width:90px}
.mat-specs{margin-top:12px}
.mat-specs-title{font-size:12px;color:#888;margin-bottom:6px}
.mat-specs-grid{display:flex;flex-wrap:wrap;gap:6px}
.mat-spec{background:#f5f7ff;border:1px solid #e0e7ff;border-radius:4px;padding:3px 8px;font-size:12px;color:#333}
.mat-spec b{color:#4f46e5}
.mat-specs-pre{background:#f8f8f8;border-radius:6px;padding:8px;font-size:11px;overflow-x:auto;white-space:pre-wrap}
</style>
