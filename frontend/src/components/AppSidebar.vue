<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { getUser, logout, myTools, listShares, createShare, deleteShare, adminUsers, createPermissionRequest, type ShareItem, type AdminUser } from '@/api'

const props = defineProps<{ active: string; tool: string; collapsed?: boolean; mobile?: boolean }>()
const emit = defineEmits<{
  (e: 'navigate', view: string): void
  (e: 'selectTool', tool: string): void
  (e: 'demoProject', pid: string): void
  (e: 'toggle'): void
}>()
const store = useAppStore()

const projTree = computed(() => {
  const ps: any[] = store.projects || []
  const tops = ps.filter(p => !p.parent)
  const kids = ps.filter(p => p.parent)
  return tops.map(t => ({ ...t, children: kids.filter(k => k.parent === t.project_id) }))
})
const expanded = ref<Record<string, boolean>>({})

const isAdmin = computed(() => getUser()?.role === 'admin')

const navItems = computed(() => {
  const items = [
    { key: 'design', label: '设计', icon: '🎨' },
    { key: 'demo', label: '演示', icon: '🎬' },
    { key: 'tools', label: '工具箱', icon: '🧰' },
    { key: 'guide', label: '指南', icon: '📖' },
    { key: 'settings', label: '设置', icon: '⚙️' },
  ]
  if (isAdmin.value) items.push({ key: 'admin', label: '管理', icon: '🛡️' })
  return items
})

// 工具授权:后端返回我可用的工具,前端过滤
const ALL_TOOLS: Record<string, { label: string; icon: string; desc: string; disabled?: boolean }> = {
  sketch: { label: '手绘草图', icon: '✏️', desc: '绘图板手绘 + 语音，AI 识别建模' },
  primitives: { label: '图元库', icon: '🧩', desc: '点选图元填参数，快速生成零件' },
  gantt: { label: '项目甘特图', icon: '📊', desc: '任务计划与里程碑，MS 风格甘特图' },
  material: { label: '标准件查询', icon: '🔩', desc: '标准件/非标件库查询(分类/品牌/规格)' },
  ocr: { label: 'OCR 识别', icon: '🔍', desc: '图片/图纸文字识别(本地免费)' },
  draft: { label: '工程画图', icon: '🗺️', desc: '上传 3D 模型(STEP),自动生成工程图纸' },
  param: { label: '参数推导', icon: '📐', desc: '从数学/物理原理推导参数', disabled: true },
  dtwin: { label: '数字孪生', icon: '🔄', desc: '运动学仿真与干涉验证', disabled: true },
}
const allowedTools = ref<Set<string>>(new Set())

const toolItems = computed(() => {
  const items: any[] = []
  for (const code of Object.keys(ALL_TOOLS)) {
    const t = ALL_TOOLS[code]
    if (t.disabled) continue
    items.push({ key: code, ...t, allowed: allowedTools.value.has(code) })
  }
  return items
})

// 共享管理
const shareOpen = ref(false)
const shareProject = ref('')
const shares = ref<ShareItem[]>([])
const allUsers = ref<AdminUser[]>([])
const shareTarget = ref('')
const sharePerm = ref<'read' | 'comment' | 'edit'>('read')
const shareMsg = ref('')

const PERM_LABEL: Record<string, string> = { read: '可读', comment: '可批注', edit: '可参与修改' }

async function openShare(p: any) {
  shareProject.value = p.project_id
  shareMsg.value = ''
  try {
    const [s, u] = await Promise.all([listShares(), adminUsers()])
    shares.value = s
    allUsers.value = u.filter(x => x.username !== getUser()?.username)
    shareOpen.value = true
  } catch (e: any) {
    shareMsg.value = e?.message || '加载失败'
  }
}

async function doShare() {
  shareMsg.value = ''
  if (!shareTarget.value) { shareMsg.value = '请选择用户'; return }
  try {
    await createShare(shareProject.value, shareTarget.value, sharePerm.value)
    shareMsg.value = '✅ 已授权'
    shares.value = await listShares()
    shareTarget.value = ''
  } catch (e: any) {
    shareMsg.value = e?.message || '授权失败'
  }
}

async function revokeShare(id: number) {
  try {
    await deleteShare(id)
    shares.value = await listShares()
  } catch (e: any) { shareMsg.value = e?.message || '撤销失败' }
}

async function loadTools() {
  try {
    const t = await myTools()
    allowedTools.value = new Set(t.map(x => x.code))
  } catch { allowedTools.value = new Set() }
}

// 工具申请弹窗
const reqOpen = ref(false)
const reqTool = ref('')
const reqReason = ref('')
const reqMsg = ref('')

function openRequest(t: any) {
  reqTool.value = t.key
  reqReason.value = ''
  reqMsg.value = ''
  reqOpen.value = true
}

async function doRequest() {
  reqMsg.value = ''
  try {
    const r = await createPermissionRequest(reqTool.value, reqReason.value)
    reqMsg.value = r.already ? '你已申请过/已有该权限' : '✅ 已提交申请,等待管理员审批'
  } catch (e: any) {
    reqMsg.value = e?.message || '申请失败'
  }
}

onMounted(loadTools)
</script>

<template>
  <div class="side" :class="{ collapsed: collapsed && !mobile, 'as-drawer': mobile && !collapsed, 'mobile-hidden': mobile && collapsed }">
    <div class="side-hd">
      <button v-if="!mobile" class="side-toggle" :title="collapsed ? '展开侧栏' : '收起侧栏'" @click="emit('toggle')">{{ collapsed ? '»' : '«' }}</button>
      <button v-else class="side-toggle" title="关闭" @click="emit('toggle')">✕</button>
      <h1 v-if="!collapsed">Anvil</h1>
      <small v-if="!collapsed">AI Mechanical Design</small>
      <div class="nav-items">
        <div v-for="item in navItems" :key="item.key"
          class="nav-item" :class="{ active: active === item.key }"
          @click="emit('navigate', item.key)">
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </div>
      </div>
    </div>
    <div class="side-projects">
      <div v-if="active === 'design'">
        <template v-for="p in projTree" :key="p.project_id">
        <div class="proj-item" :class="{ active: p.project_id === store.current }"
          @click="store.selectProject(p.project_id)">
          <span v-if="p.children.length" class="proj-fold" @click.stop="expanded[p.project_id] = !expanded[p.project_id]">{{ expanded[p.project_id] ? '▾' : '▸' }}</span>
          <span class="proj-name">{{ p.name }}</span>
          <span v-if="p.owner && p.owner !== getUser()?.username" class="phase" :title="'共享自 ' + p.owner + ' · ' + (PERM_LABEL[p.permission] || p.permission)">{{ PERM_LABEL[p.permission] || p.permission }}</span>
          <span v-else-if="p.phase" class="phase">{{ p.phase }}</span>
          <button v-if="!p.owner || p.owner === getUser()?.username" class="proj-share" title="授权共享" @click.stop="openShare(p)">🔗</button>
          <button v-if="!p.owner || p.owner === getUser()?.username" class="proj-del" title="删除项目" @click.stop="store.deleteProject(p.project_id)">🗑</button>
        </div>
        <div v-for="c in (expanded[p.project_id] ? p.children : [])" :key="c.project_id"
          class="proj-item sub" :class="{ active: c.project_id === store.current }"
          @click="store.selectProject(c.project_id)">
          <span class="proj-name">↳ {{ c.name }}</span>
        </div>
        </template>
      </div>
      <div v-else-if="active === 'demo'" v-for="p in store.projects" :key="'demo-' + p.project_id"
        class="proj-item" @click="emit('demoProject', p.project_id)">
        <span class="proj-name">🎬 {{ p.name }}</span>
      </div>
      <div v-else-if="active === 'tools'" class="nav-tools">
        <div v-for="t in toolItems" :key="t.key"
          class="nav-tool" :class="{ active: tool === t.key, locked: !t.allowed }"
          @click="t.allowed && emit('selectTool', t.key)">
          <span class="nav-tool-icon">{{ t.icon }}</span>
          <span class="nav-tool-name">{{ t.label }}</span>
          <button v-if="!t.allowed" class="nav-tool-req" @click.stop="openRequest(t)" title="申请">申请</button>
        </div>
      </div>
      <div v-else-if="active === 'settings'" class="nav-placeholder">
        <p>设置</p>
      </div>
    </div>
    <div v-if="active === 'design'" class="new-proj" @click="store.showModal = true">+ New Project</div>

    <!-- 登出:登录后所有视图都可见(侧边栏底部) -->
    <div class="side-foot">
      <span class="side-user" :title="getUser()?.username">👤 {{ getUser()?.username || '' }}</span>
      <button class="side-logout" @click="logout()" title="退出登录">🚪 退出</button>
    </div>

    <!-- 工具申请弹窗 -->
    <div v-if="reqOpen" class="share-mask" @click.self="reqOpen = false">
      <div class="share-modal">
        <h4>🔐 申请工具权限</h4>
        <p class="share-proj">工具: {{ ALL_TOOLS[reqTool]?.label || reqTool }}</p>
        <div class="share-form">
          <input v-model="reqReason" placeholder="申请理由(选填)" class="share-input" />
          <button class="share-btn" @click="doRequest" title="提交申请">提交申请</button>
        </div>
        <p v-if="reqMsg" class="share-msg">{{ reqMsg }}</p>
        <button class="share-close" @click="reqOpen = false" title="关闭弹窗">关闭</button>
      </div>
    </div>

    <!-- 共享管理弹窗 -->
    <div v-if="shareOpen" class="share-mask" @click.self="shareOpen = false">
      <div class="share-modal">
        <h4>🔗 共享项目</h4>
        <p class="share-proj">{{ shareProject }}</p>
        <div class="share-form">
          <select v-model="shareTarget" class="share-input">
            <option value="">选择用户...</option>
            <option v-for="u in allUsers" :key="u.id" :value="u.username">{{ u.username }}({{ u.display_name }})</option>
          </select>
          <select v-model="sharePerm" class="share-input">
            <option value="read">可读</option>
            <option value="comment">可批注(读+批注)</option>
            <option value="edit">可参与修改(读+写+生成)</option>
          </select>
          <button class="share-btn" @click="doShare" title="授权共享">授权</button>
        </div>
        <p v-if="shareMsg" class="share-msg">{{ shareMsg }}</p>
        <div class="share-list">
          <div v-for="s in shares.filter(x => x.project_id === shareProject)" :key="s.id" class="share-item">
            <span>{{ s.target_username }}</span>
            <span class="share-perm">{{ PERM_LABEL[s.permission] }}</span>
            <button class="share-revoke" @click="revokeShare(s.id)" title="撤销共享">撤销</button>
          </div>
          <p v-if="!shares.filter(x => x.project_id === shareProject).length" class="share-empty">尚未授权</p>
        </div>
        <button class="share-close" @click="shareOpen = false" title="关闭弹窗">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.side{width:260px;background:#f5f5f5;border-right:1px solid #e5e5e5;display:flex;flex-direction:column;flex-shrink:0}
.side-hd{position:relative;padding:16px 16px 8px;border-bottom:1px solid #e5e5e5}
.side-hd h1{font-size:16px;font-weight:700;color:#4f46e5}
.side-hd small{font-size:10px;color:#999}
.nav-items{display:flex;flex-wrap:wrap;gap:4px;margin-top:12px}
.nav-item{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:13px;color:#555;flex:1;justify-content:center}
.nav-item:hover{background:#e8e8ea}
.nav-item.active{background:#e0e7ff;color:#4f46e5;font-weight:600}
.nav-icon{font-size:14px}
.side-projects{flex:1;overflow-y:auto;padding:4px 0}
.proj-item{display:flex;align-items:center;padding:8px 12px;margin:1px 0;border-radius:6px;cursor:pointer;font-size:13px;color:#333;gap:6px}
.proj-item:hover{background:#e8e8ea}
.proj-item.active{background:#e0e7ff;color:#4f46e5;font-weight:600}
.proj-item .phase{font-size:10px;color:#999;flex-shrink:0}
.proj-item .proj-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.proj-item .proj-del,.proj-item .proj-share{background:none;border:none;font-size:12px;cursor:pointer;opacity:0;padding:2px 4px;border-radius:4px;flex-shrink:0}
.proj-item:hover .proj-del,.proj-item:hover .proj-share{opacity:0.5}
.proj-item .proj-del:hover{opacity:1;background:#fee2e2}
.proj-item .proj-share:hover{opacity:1;background:#e0e7ff}
.new-proj{margin:8px 12px;padding:8px;border:1px dashed #d1d5db;border-radius:8px;text-align:center;font-size:12px;color:#6b7280;cursor:pointer}
.new-proj:hover{border-color:#4f46e5;color:#4f46e5;background:#fff}
.side-foot{display:flex;align-items:center;gap:8px;padding:10px 12px;border-top:1px solid #e5e5e5;margin-top:auto}
.side-user{font-size:12px;color:#666;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.side-logout{background:#fff;border:1px solid #e5e5e5;border-radius:6px;padding:4px 10px;font-size:12px;color:#555;cursor:pointer;flex-shrink:0}
.side-logout:hover{color:#dc2626;border-color:#fecaca;background:#fef2f2}
.nav-placeholder{padding:24px;text-align:center;color:#999;font-size:12px}
.nav-tools{padding:6px 8px}
.nav-tool{display:flex;align-items:center;gap:8px;padding:9px 10px;border-radius:8px;cursor:pointer;font-size:13px;color:#333;transition:all .12s;margin-bottom:2px}
.nav-tool:hover{background:#e8e8ea}
.nav-tool.active{background:#e0e7ff;color:#4f46e5;font-weight:600}
.nav-tool.disabled{opacity:.45;cursor:not-allowed}
.nav-tool.locked{opacity:.6}
.nav-tool-req{background:#e0e7ff;color:#4f46e5;border:none;border-radius:4px;padding:1px 8px;font-size:10px;cursor:pointer;flex-shrink:0}
.nav-tool-req:hover{background:#c7d2fe}
.nav-tool-icon{font-size:15px;flex-shrink:0}
.nav-tool-name{flex:1}
.nav-tool-badge{font-size:8px;color:#999;background:#f3f4f6;padding:1px 5px;border-radius:4px}
.share-mask{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:120;display:flex;align-items:center;justify-content:center}
.share-modal{background:#fff;border-radius:10px;padding:20px 24px;min-width:380px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
.share-modal h4{margin:0 0 6px;font-size:15px;color:#333}
.share-proj{font-size:12px;color:#666;margin:0 0 12px;font-family:monospace}
.share-form{display:flex;gap:6px;margin-bottom:8px}
.share-input{border:1px solid #d0d0d4;border-radius:6px;padding:6px 8px;font-size:12px;flex:1}
.share-btn{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer}
.share-msg{font-size:12px;color:#059669;margin:4px 0}
.share-list{margin:8px 0;max-height:200px;overflow-y:auto}
.share-item{display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid #e5e5e5;border-radius:6px;margin-bottom:4px;font-size:12px}
.share-item .share-perm{font-size:11px;color:#4f46e5;background:#eef2ff;padding:1px 8px;border-radius:10px}
.share-item .share-revoke{margin-left:auto;background:none;border:none;color:#dc2626;font-size:12px;cursor:pointer}
.share-empty{font-size:12px;color:#aaa;text-align:center;padding:10px}
.share-close{width:100%;background:#f3f4f6;border:1px solid #e5e5e5;border-radius:6px;padding:6px;font-size:12px;cursor:pointer}

/* 收起(桌面):窄条仅图标 */
/* 折叠按钮:放大加底色,清晰可见 */
.side-toggle{background:#eef0ff;border:1px solid #b9c2f5;color:#4f46e5;font-size:18px;font-weight:700;cursor:pointer;width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;position:absolute;top:12px;right:12px;transition:all .15s}
.side-toggle:hover{background:#4f46e5;color:#fff;border-color:#4f46e5;transform:scale(1.08)}
.side.collapsed{width:56px;overflow:hidden}
.side.collapsed .nav-label,.side.collapsed .side-projects,.side.collapsed small{display:none}
.side.collapsed .nav-item{justify-content:center;padding:10px 0}
.side.collapsed .side-hd{padding-top:34px}
/* 抽屉(移动,类驱动由 App 传 mobile/collapsed):
   .side.mobile-hidden = 移出屏幕; .as-drawer = 滑入 */
.side.mobile-hidden{position:fixed;left:0;top:0;bottom:0;z-index:1001;width:240px;transform:translateX(-100%);transition:transform .25s}
.side.as-drawer{position:fixed;left:0;top:0;bottom:0;z-index:1001;width:240px;transform:translateX(0);transition:transform .25s;box-shadow:4px 0 24px rgba(0,0,0,.4)}
.proj-fold{cursor:pointer;width:14px;color:#999;flex-shrink:0}
.proj-item.sub{padding-left:26px}
</style>
