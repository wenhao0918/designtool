<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminUsers, adminCreateUser, adminUpdateUser, adminDeleteUser, adminLoginLogs, adminLogs, designLogRollback, listTerms, createTerm, updateTerm, deleteTerm, adminRoles, adminTools, setRoleTool, setUserTool, adminTokenUsage, putModelConfigBatch, adminRequests, approveRequest, rejectRequest, type AdminUser, type LoginLogItem, type AdminLogs, type RoleItem, type ToolAuthData, type TokenUsageSummary, type PermissionRequestItem, type MechTerm } from '@/api'

defineOptions({ name: 'AdminView' })

const tab = ref<'users' | 'requests' | 'auth' | 'usage' | 'loginlogs' | 'logs' | 'terms'>('users')
const users = ref<AdminUser[]>([])
const loginLogs = ref<LoginLogItem[]>([])
const auditLogs = ref<AdminLogs>({ downloads: [], design: [] })
const roles = ref<RoleItem[]>([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

// 机械设计术语表
const terms = ref<MechTerm[]>([])
const termMsg = ref('')
const editingTerm = ref<MechTerm | null>(null)
const termForm = ref({ term: '', definition: '', geometry: '', modeling: '' })

async function loadTerms() {
  try { terms.value = await listTerms() } catch (e: any) { termMsg.value = '加载失败: ' + e?.message }
}
function termEdit(t: MechTerm) {
  editingTerm.value = { ...t }
  termForm.value = { term: t.term, definition: t.definition, geometry: t.geometry, modeling: t.modeling }
}
function termNew() {
  editingTerm.value = { id: 0, term: '', definition: '', geometry: '', modeling: '' }
  termForm.value = { term: '', definition: '', geometry: '', modeling: '' }
}
async function termSave() {
  termMsg.value = ''
  if (!termForm.value.term.trim()) { termMsg.value = '术语名不能为空'; return }
  try {
    if (editingTerm.value && editingTerm.value.id) {
      await updateTerm(editingTerm.value.id, termForm.value)
      termMsg.value = '✅ 已更新'
    } else {
      await createTerm(termForm.value)
      termMsg.value = '✅ 已新增'
    }
    editingTerm.value = null
    await loadTerms()
  } catch (e: any) { termMsg.value = '保存失败: ' + (e?.message || e) }
}
async function termDelete(t: MechTerm) {
  if (!confirm(`删除术语「${t.term}」？`)) return
  try {
    await deleteTerm(t.id)
    termMsg.value = '✅ 已删除'
    await loadTerms()
  } catch (e: any) { termMsg.value = '删除失败: ' + (e?.message || e) }
}

// 新建用户弹窗
const showCreate = ref(false)
const newUser = ref({ username: '', password: '', display_name: '', role: 'viewer' })
// 重置密码
const resetPwd = ref<{ id: number; username: string; password: string } | null>(null)

const ROLE_LABEL: Record<string, string> = { admin: '管理员', engineer: '工程师', viewer: '访客' }

async function rollbackTo(seq: number, project: string, instruction: string) {
  if (!confirm(`从设计日志第 ${seq} 步重新设计？\n\n该步: ${(instruction || '').slice(0, 60)}\n\n模型将恢复到该步开始前的状态，后续指令基于此状态增量修改。`)) return
  try {
    const r = await designLogRollback(project, seq)
    alert('✅ ' + (r?.message || `已恢复到第 ${seq} 步`))
    await loadAll()
  } catch (e: any) {
    alert('回滚失败: ' + (e?.message || e))
  }
}
const toolAuth = ref<ToolAuthData>({ tools: [], role_tools: [], user_tools: [] })
const authMsg = ref('')
const usage = ref<TokenUsageSummary>({ days: 7, total_tokens: 0, by_user: [], by_kind: [] })
const requests = ref<PermissionRequestItem[]>([])
const reqStatus = ref('pending')

async function loadRequests() {
  try { requests.value = await adminRequests(reqStatus.value) } catch (e: any) { authMsg.value = e?.message || '加载申请失败' }
}
async function doApprove(id: number) {
  try { await approveRequest(id); msg.value = '✅ 已审批通过并授权'; await loadRequests(); await loadAll() }
  catch (e: any) { error.value = e?.message || '审批失败' }
}
async function doReject(id: number) {
  try { await rejectRequest(id); msg.value = '已拒绝'; await loadRequests() }
  catch (e: any) { error.value = e?.message || '拒绝失败' }
}
const usageDays = ref(7)
const batchOpen = ref(false)
const batchCfg = ref({ usernames: '', base_url: '', api_key: '', model: '', kind: 'inference' })
const batchMsg = ref('')

async function loadUsage() {
  try { usage.value = await adminTokenUsage(usageDays.value) } catch (e: any) { authMsg.value = e?.message || '加载用量失败' }
}
async function doBatch() {
  batchMsg.value = ''
  const names = batchCfg.value.usernames.split(',').map(x => x.trim()).filter(Boolean)
  if (!names.length || !batchCfg.value.api_key) { batchMsg.value = '请填用户名(逗号分隔)和 API Key'; return }
  try {
    const item = { base_url: batchCfg.value.base_url, api_key: batchCfg.value.api_key, model: batchCfg.value.model }
    await putModelConfigBatch(names, { [batchCfg.value.kind]: item } as any)
    batchMsg.value = '✅ 已批量配置 ' + names.length + ' 个用户'
  } catch (e: any) { batchMsg.value = e?.message || '配置失败' }
}

function hasRoleTool(role: string, tool: string): boolean {
  return toolAuth.value.role_tools.some(x => x.role_code === role && x.tool_code === tool)
}
function hasUserTool(uid: number, tool: string): boolean {
  const u = toolAuth.value.user_tools.find(x => x.user_id === uid && x.tool_code === tool)
  return u ? u.granted === 1 : false
}
async function toggleRoleTool(role: string, tool: string, on: boolean) {
  try {
    await setRoleTool(role, tool, on)
    toolAuth.value = await adminTools()
    authMsg.value = `已${on ? '授权' : '回收'} ${tool} → ${ROLE_LABEL[role] || role}`
  } catch (e: any) { authMsg.value = e?.message || '操作失败' }
}
async function toggleUserTool(uid: number, tool: string, on: boolean) {
  try {
    await setUserTool(uid, tool, on)
    toolAuth.value = await adminTools()
    authMsg.value = `已${on ? '额外授权' : '禁止'} ${tool}`
  } catch (e: any) { authMsg.value = e?.message || '操作失败' }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  msg.value = ''
  try {
    const [u, l, a, r, t] = await Promise.all([adminUsers(), adminLoginLogs(), adminLogs(), adminRoles(), adminTools()])
    users.value = u
    loginLogs.value = l
    auditLogs.value = a
    roles.value = r
    toolAuth.value = t
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function roleName(code: string): string {
  const r = roles.value.find(x => x.code === code)
  return r ? r.name : (ROLE_LABEL[code] || code)
}

async function doCreate() {
  try {
    await adminCreateUser({ ...newUser.value })
    msg.value = `已创建用户 ${newUser.value.username}`
    showCreate.value = false
    newUser.value = { username: '', password: '', display_name: '', role: 'viewer' }
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || '创建失败'
  }
}

async function setRole(u: AdminUser, role: string) {
  try {
    await adminUpdateUser(u.id, { role })
    msg.value = `已设置 ${u.username} 角色为 ${roleName(role)}`
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || '操作失败'
  }
}

async function toggleStatus(u: AdminUser) {
  try {
    const st = u.status === 'active' ? 'disabled' : 'active'
    await adminUpdateUser(u.id, { status: st })
    msg.value = `已${st === 'active' ? '启用' : '停用'} ${u.username}`
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || '操作失败'
  }
}

async function toggleTestUser(u: AdminUser) {
  try {
    await adminUpdateUser(u.id, { is_test: !u.is_test })
    msg.value = u.is_test ? `已取消 ${u.username} 测试用户(需自配模型)` : `已设 ${u.username} 为测试用户(可用默认模型)`
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || '操作失败'
  }
}

async function doResetPwd() {
  if (!resetPwd.value) return
  try {
    await adminUpdateUser(resetPwd.value.id, { password: resetPwd.value.password })
    msg.value = `已重置 ${resetPwd.value.username} 的密码`
    resetPwd.value = null
  } catch (e: any) {
    error.value = e?.message || '重置失败'
  }
}

async function delUser(u: AdminUser) {
  if (!confirm(`确认删除用户 ${u.username}？此操作不可恢复。`)) return
  try {
    await adminDeleteUser(u.id)
    msg.value = `已删除 ${u.username}`
    await loadAll()
  } catch (e: any) {
    error.value = e?.message || '删除失败'
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="admin-view">
    <div class="admin-hd">
      <h3>🛡️ 管理</h3>
      <span class="admin-sub">仅管理员 · 用户分级 / 登录日志 / 系统日志</span>
      <button class="btn-refresh" @click="loadAll" title="自动旋转">⟳ 刷新</button>
      <div class="admin-tabs">
        <button class="tab-btn" title="用户管理" :class="{ active: tab === 'users' }" @click="tab = 'users'">👤 用户管理 ({{ users.length }})</button>
        <button class="tab-btn" title="权限申请审批" :class="{ active: tab === 'requests' }" @click="loadRequests(); tab = 'requests'">📨 权限申请 ({{ requests.filter(r => r.status === 'pending').length }})</button>
        <button class="tab-btn" :class="{ active: tab === 'auth' }" @click="tab = 'auth'" title="授权共享">🔐 工具授权</button>
        <button class="tab-btn" title="Token 消耗" :class="{ active: tab === 'usage' }" @click="loadUsage(); tab = 'usage'">⚡ Token 消耗</button>
        <button class="tab-btn" :class="{ active: tab === 'loginlogs' }" @click="tab = 'loginlogs'" title="登录">🔑 登录日志 ({{ loginLogs.length }})</button>
        <button class="tab-btn" :class="{ active: tab === 'logs' }" @click="tab = 'logs'" title="复制">📋 系统日志</button>
        <button class="tab-btn" :class="{ active: tab === 'terms' }" @click="loadTerms(); tab = 'terms'" title="机械设计术语表">📖 术语表 ({{ terms.length }})</button>
      </div>
    </div>

    <div v-if="error" class="admin-error">{{ error }}</div>
    <div v-if="msg" class="admin-msg">{{ msg }}</div>
    <div v-if="loading" class="admin-empty">加载中…</div>

    <!-- 用户管理 -->
    <div v-else-if="tab === 'users'" class="admin-body">
      <div class="users-toolbar">
        <span class="users-hint">用户分级: 管理员(全部) / 工程师(设计) / 访客(只读) · 测试用户可用默认模型,普通用户须自配推理/视觉模型</span>
        <button class="btn-add" @click="showCreate = true" title="新建">＋ 新建用户</button>
      </div>
      <table class="admin-table">
        <thead>
          <tr><th>ID</th><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>测试用户</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.id }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.display_name }}</td>
            <td>
              <select :value="u.role" @change="setRole(u, ($event.target as HTMLSelectElement).value)">
                <option v-for="r in roles" :key="r.code" :value="r.code">{{ r.name }}</option>
              </select>
            </td>
            <td><span class="badge" :class="u.status">{{ u.status === 'active' ? '正常' : '停用' }}</span></td>
            <td><span class="badge" :class="u.is_test ? 'active' : 'disabled'">{{ u.is_test ? '是' : '否' }}</span></td>
            <td class="col-time">{{ u.created_at.slice(0, 19).replace('T', ' ') }}</td>
            <td class="ops">
              <button class="mini" @click="toggleTestUser(u)" :title="u.is_test ? '取消测试用户:须自配模型' : '设为测试用户:可用默认模型'">{{ u.is_test ? '取消测试' : '设为测试' }}</button>
              <button class="mini" @click="toggleStatus(u)" title="停用账号">{{ u.status === 'active' ? '停用' : '启用' }}</button>
              <button class="mini" @click="resetPwd = { id: u.id, username: u.username, password: '' }" title="重置用户密码">重置密码</button>
              <button class="mini danger" @click="delUser(u)" title="删除">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 权限申请审批 -->
    <div v-else-if="tab === 'requests'" class="admin-body">
      <div class="users-toolbar">
        <span class="users-hint">用户申请工具权限,审批通过自动完成授权</span>
        <select v-model="reqStatus" @change="loadRequests" class="filter-select">
          <option value="pending">待审批</option>
          <option value="approved">已通过</option>
          <option value="rejected">已拒绝</option>
          <option value="all">全部</option>
        </select>
      </div>
      <table class="admin-table">
        <thead><tr><th>时间</th><th>用户</th><th>工具</th><th>理由</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="r in requests" :key="r.id">
            <td class="col-time">{{ r.created_at.slice(0, 19).replace('T', ' ') }}</td>
            <td>{{ r.username }}</td>
            <td>{{ r.tool_code }}</td>
            <td class="col-reason" :title="r.reason">{{ r.reason || '—' }}</td>
            <td><span class="badge" :class="r.status">{{ r.status === 'pending' ? '待审批' : r.status === 'approved' ? '已通过' : '已拒绝' }}</span></td>
            <td class="ops">
              <template v-if="r.status === 'pending'">
                <button class="mini ok" @click="doApprove(r.id)" title="审批通过">通过</button>
                <button class="mini danger" @click="doReject(r.id)" title="拒绝申请">拒绝</button>
              </template>
              <span v-else class="col-time">{{ r.reviewed_by || '' }}</span>
            </td>
          </tr>
          <tr v-if="!requests.length"><td colspan="6" class="admin-empty">暂无申请</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 工具授权 -->
    <div v-else-if="tab === 'auth'" class="admin-body">
      <p v-if="authMsg" class="admin-msg">{{ authMsg }}</p>
      <div class="logs-section">
        <h4>角色-工具授权(勾选=角色默认可用)</h4>
        <table class="admin-table">
          <thead><tr><th>工具</th><th v-for="r in roles" :key="r.code">{{ r.name }}</th></tr></thead>
          <tbody>
            <tr v-for="t in toolAuth.tools" :key="t.code">
              <td>{{ t.name }}<span class="tool-code">({{ t.code }})</span></td>
              <td v-for="r in roles" :key="r.code" class="chk-cell">
                <input type="checkbox" :checked="hasRoleTool(r.code, t.code)" @change="toggleRoleTool(r.code, t.code, ($event.target as HTMLInputElement).checked)" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="logs-section">
        <h4>用户-工具授权(个别覆盖:额外授予/禁止)</h4>
        <table class="admin-table">
          <thead><tr><th>用户</th><th v-for="t in toolAuth.tools" :key="t.code">{{ t.name }}</th></tr></thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>{{ u.username }}<span class="tool-code">({{ ROLE_LABEL[u.role] || u.role }})</span></td>
              <td v-for="t in toolAuth.tools" :key="t.code" class="chk-cell">
                <input type="checkbox" :checked="hasUserTool(u.id, t.code)" @change="toggleUserTool(u.id, t.code, ($event.target as HTMLInputElement).checked)" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Token 消耗 -->
    <div v-else-if="tab === 'usage'" class="admin-body">
      <div class="users-toolbar">
        <span class="users-hint">近 {{ usage.days }} 天 token 消耗(推理/视觉)</span>
        <select v-model="usageDays" @change="loadUsage" class="filter-select">
          <option :value="1">近1天</option><option :value="7">近7天</option><option :value="30">近30天</option>
        </select>
        <button class="btn-add" @click="batchOpen = true">⚙️ 批量配置模型 Key</button>
      </div>
      <div class="usage-total">总消耗: <b>{{ usage.total_tokens.toLocaleString() }}</b> tokens</div>
      <div class="logs-section">
        <h4>按用户</h4>
        <table class="admin-table">
          <thead><tr><th>用户</th><th>调用次数</th><th>输入</th><th>输出</th><th>总计</th></tr></thead>
          <tbody>
            <tr v-for="u in usage.by_user" :key="u.username">
              <td>{{ u.username }}</td><td>{{ u.calls }}</td><td>{{ u.prompt.toLocaleString() }}</td><td>{{ u.completion.toLocaleString() }}</td><td><b>{{ u.total.toLocaleString() }}</b></td>
            </tr>
            <tr v-if="!usage.by_user.length"><td colspan="5" class="admin-empty">暂无消耗记录</td></tr>
          </tbody>
        </table>
      </div>
      <div class="logs-section">
        <h4>按模型类型</h4>
        <table class="admin-table">
          <thead><tr><th>类型</th><th>调用次数</th><th>输入</th><th>输出</th><th>总计</th></tr></thead>
          <tbody>
            <tr v-for="k in usage.by_kind" :key="k.kind">
              <td>{{ k.kind }}</td><td>{{ k.calls }}</td><td>{{ k.prompt.toLocaleString() }}</td><td>{{ k.completion.toLocaleString() }}</td><td><b>{{ k.total.toLocaleString() }}</b></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 登录日志 -->
    <div v-else-if="tab === 'loginlogs'" class="admin-body">
      <table class="admin-table">
        <thead><tr><th>时间</th><th>用户</th><th>结果</th><th>IP</th><th>详情</th><th>UA</th></tr></thead>
        <tbody>
          <tr v-for="l in loginLogs" :key="l.id">
            <td class="col-time">{{ l.time.slice(0, 19).replace('T', ' ') }}</td>
            <td>{{ l.username }}</td>
            <td><span class="badge" :class="l.success ? 'active' : 'disabled'">{{ l.success ? '成功' : '失败' }}</span></td>
            <td>{{ l.ip }}</td>
            <td>{{ l.detail }}</td>
            <td class="col-ua" :title="l.user_agent">{{ l.user_agent }}</td>
          </tr>
          <tr v-if="!loginLogs.length"><td colspan="6" class="admin-empty">暂无登录记录</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 系统日志(下载追溯 + 设计日志) -->
    <div v-else-if="tab === 'logs'" class="admin-body">
      <div class="logs-section">
        <h4>⬇ 下载追溯日志 ({{ auditLogs.downloads.length }})</h4>
        <table class="admin-table">
          <thead><tr><th>时间</th><th>用户</th><th>项目</th><th>文件</th><th>动作</th><th>大小</th></tr></thead>
          <tbody>
            <tr v-for="(d, i) in auditLogs.downloads.slice(0, 200)" :key="i">
              <td class="col-time">{{ d.time }}</td><td>{{ d.username }}</td>
              <td class="col-proj">{{ d.project }}</td>
              <td class="col-file" :title="d.file">{{ d.file }}</td>
              <td><span class="badge" :class="d.action">{{ d.action }}</span></td>
              <td>{{ d.size }}</td>
            </tr>
            <tr v-if="!auditLogs.downloads.length"><td colspan="6" class="admin-empty">暂无下载记录</td></tr>
          </tbody>
        </table>
      </div>
      <div class="logs-section">
        <h4>🧩 设计日志 ({{ auditLogs.design.length }})</h4>
        <table class="admin-table">
          <thead><tr><th>#</th><th>时间</th><th>用户</th><th>项目</th><th>动作</th><th>设计指示</th><th>LLM 回应</th><th>结果目录</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(d, i) in auditLogs.design.slice(0, 200)" :key="i">
              <td class="col-seq">{{ d.seq }}</td>
              <td class="col-time">{{ d.time.slice(0, 19).replace('T', ' ') }}</td><td>{{ d.username }}</td>
              <td class="col-proj">{{ d.project }}</td>
              <td>{{ d.action }}</td>
              <td class="col-instruction" :title="d.instruction">{{ d.instruction }}</td>
              <td class="col-llm" :title="d.llm_response">{{ d.llm_response }}</td>
              <td class="col-out" :title="d.output_dir">{{ d.output_dir }}</td>
              <td><button class="btn-rollback" title="从这一步重新设计" @click="rollbackTo(d.seq, d.project, d.instruction)">↩ 重设计</button></td>
            </tr>
            <tr v-if="!auditLogs.design.length"><td colspan="9" class="admin-empty">暂无设计日志</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 机械设计术语表 -->
    <div v-else-if="tab === 'terms'" class="admin-body">
      <div class="logs-section">
        <div class="terms-hd">
          <h4>📖 机械设计术语表 ({{ terms.length }})</h4>
          <button class="btn-add" @click="termNew" title="新增术语">＋ 新增术语</button>
        </div>
        <p class="terms-hint">这些术语会注入 Anvil 的系统提示词并支持 lookup_term 查询,帮助 AI 正确理解专业术语。</p>
        <p v-if="termMsg" class="terms-msg">{{ termMsg }}</p>
        <div v-if="editingTerm" class="terms-form">
          <input v-model="termForm.term" placeholder="术语名(如:退刀槽)" class="modal-input" />
          <textarea v-model="termForm.definition" placeholder="定义(专业含义)" class="terms-textarea" rows="2"></textarea>
          <textarea v-model="termForm.geometry" placeholder="几何(在3D模型中的几何特征)" class="terms-textarea" rows="2"></textarea>
          <textarea v-model="termForm.modeling" placeholder="建模(用原语建模的指导:方向/深度/刀具选择)" class="terms-textarea" rows="3"></textarea>
          <div class="terms-btns">
            <button class="btn-add" @click="termSave" title="保存">保存</button>
            <button class="btn-sec" @click="editingTerm = null" title="取消">取消</button>
          </div>
        </div>
        <table class="admin-table">
          <thead><tr><th>术语</th><th>定义</th><th>几何</th><th>建模指导</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="t in terms" :key="t.id">
              <td class="term-name">{{ t.term }}</td>
              <td class="term-cell" :title="t.definition">{{ t.definition }}</td>
              <td class="term-cell" :title="t.geometry">{{ t.geometry }}</td>
              <td class="term-cell" :title="t.modeling">{{ t.modeling }}</td>
              <td class="ops">
                <button class="mini" @click="termEdit(t)" title="编辑">✏️</button>
                <button class="mini term-del" @click="termDelete(t)" title="删除">🗑</button>
              </td>
            </tr>
            <tr v-if="!terms.length"><td colspan="5" class="admin-empty">暂无术语</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新建用户弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h4>新建用户</h4>
        <input v-model="newUser.username" placeholder="用户名" class="modal-input" />
        <input v-model="newUser.password" type="password" placeholder="密码(至少4位)" class="modal-input" />
        <input v-model="newUser.display_name" placeholder="显示名(可选)" class="modal-input" />
        <select v-model="newUser.role" class="modal-input">
          <option v-for="r in roles" :key="r.code" :value="r.code">{{ r.name }}({{ r.description }})</option>
        </select>
        <div class="modal-btns">
          <button class="btn-sec" @click="showCreate = false" title="取消">取消</button>
          <button class="btn-add" @click="doCreate" title="创建项目">创建</button>
        </div>
      </div>
    </div>

    <!-- 批量配置模型 Key 弹窗 -->
    <div v-if="batchOpen" class="modal-mask" @click.self="batchOpen = false">
      <div class="modal" style="min-width:420px">
        <h4>⚙️ 批量配置模型 Key(测试用户统一配置)</h4>
        <input v-model="batchCfg.usernames" placeholder="用户名,逗号分隔(如 test1,test2,test3)" class="modal-input" />
        <select v-model="batchCfg.kind" class="modal-input">
          <option value="inference">推理</option>
          <option value="vision">视觉</option>
          <option value="voice">语音</option>
        </select>
        <input v-model="batchCfg.base_url" placeholder="Base URL(如 https://api.deepseek.com/v1)" class="modal-input" />
        <input v-model="batchCfg.api_key" type="password" placeholder="API Key" class="modal-input" />
        <input v-model="batchCfg.model" placeholder="模型名(如 deepseek-v4-flash)" class="modal-input" />
        <p v-if="batchMsg" class="pwd-ok">{{ batchMsg }}</p>
        <div class="modal-btns">
          <button class="btn-sec" @click="batchOpen = false" title="关闭弹窗">关闭</button>
          <button class="btn-add" @click="doBatch" title="应用配置">应用</button>
        </div>
      </div>
    </div>

    <!-- 重置密码弹窗 -->
    <div v-if="resetPwd" class="modal-mask" @click.self="resetPwd = null">
      <div class="modal">
        <h4>重置密码: {{ resetPwd.username }}</h4>
        <input v-model="resetPwd.password" type="password" placeholder="新密码(至少4位)" class="modal-input" @keyup.enter="doResetPwd" />
        <div class="modal-btns">
          <button class="btn-sec" @click="resetPwd = null" title="取消">取消</button>
          <button class="btn-add" @click="doResetPwd" title="确认">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-view{flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;padding:16px 20px;overflow:hidden}
.admin-hd{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.admin-hd h3{font-size:16px;font-weight:700;color:#333;margin:0}
.admin-sub{font-size:11px;color:#999}
.btn-refresh{margin-left:auto;background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}
.admin-tabs{display:flex;gap:8px;width:100%}
.tab-btn{background:#f3f4f6;border:1px solid #e5e5e5;border-radius:6px;padding:6px 14px;font-size:12px;cursor:pointer;color:#555}
.tab-btn.active{background:#e0e7ff;color:#4f46e5;font-weight:600;border-color:#4f46e5}
.admin-body{flex:1;overflow:auto;border:1px solid #e5e5e5;border-radius:8px;padding:12px}
.admin-error{color:#dc2626;font-size:13px;padding:8px 0}
.admin-msg{color:#059669;font-size:13px;padding:8px 0}
.admin-empty{color:#aaa;text-align:center;padding:30px 0;font-size:13px}
.users-toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.users-hint{font-size:11px;color:#888}
.btn-add{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}
.admin-table{width:100%;border-collapse:collapse;font-size:12px}
.admin-table th{background:#f8f8f8;font-size:11px;color:#888;text-align:left;padding:7px 10px;border-bottom:1px solid #e5e5e5;position:sticky;top:0;z-index:2}
.admin-table td{padding:6px 10px;border-bottom:1px solid #f0f0f0;vertical-align:middle}
.admin-table tr:hover td{background:#f5f7ff}
.admin-table select{border:1px solid #d0d0d4;border-radius:5px;padding:2px 6px;font-size:12px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px}
.badge.active{background:#ecfdf5;color:#059669}
.badge.disabled{background:#fee2e2;color:#dc2626}
.badge.download{background:#ecfdf5;color:#059669}
.badge.view{background:#eff6ff;color:#2563eb}
.col-time{white-space:nowrap;color:#666;font-family:monospace;font-size:11px}
.chk-cell{text-align:center}
.usage-total{font-size:16px;color:#333;margin-bottom:10px}
.usage-total b{color:#4f46e5}
.tool-code{font-size:10px;color:#aaa;margin-left:4px}
.col-proj{max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.col-file{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:monospace;font-size:11px}
.col-ua{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#888}
.col-instruction{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.col-llm{max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#666}
.col-out{max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:monospace;font-size:11px;color:#444}
.col-seq{width:36px;text-align:center;font-weight:700;color:#4f46e5;font-family:monospace}
.btn-rollback{background:#fff7ed;border:1px solid #fdba74;color:#ea580c;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;white-space:nowrap}
.btn-rollback:hover{background:#ffedd5}
.ops{white-space:nowrap}
.mini{background:#fff;border:1px solid #d0d0d4;border-radius:5px;padding:2px 8px;font-size:11px;cursor:pointer;margin-right:4px;color:#555}
.mini:hover{background:#f0f0f4}
.terms-hd{display:flex;align-items:center;gap:12px;margin-bottom:4px}
.terms-hd h4{margin:0}
.terms-hint{font-size:11px;color:#999;margin:0 0 8px}
.terms-msg{font-size:12px;color:#059669;margin:4px 0}
.terms-form{display:flex;flex-direction:column;gap:6px;padding:10px;border:1px solid #e5e5e5;border-radius:8px;background:#fafafa;margin-bottom:10px}
.terms-textarea{border:1px solid #d0d0d4;border-radius:6px;padding:6px 8px;font-size:12px;font-family:inherit;resize:vertical;width:100%}
.terms-btns{display:flex;gap:8px}
.terms-btns .btn-add,.terms-btns .btn-sec{padding:5px 16px}
.term-name{font-weight:700;color:#4f46e5;white-space:nowrap}
.term-cell{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#444}
.term-del:hover{color:#dc2626;background:#fee2e2}
.mini.danger{color:#dc2626;border-color:#fca5a5}
.mini.danger:hover{background:#fee2e2}
.mini.ok{color:#059669;border-color:#a7f3d0}
.mini.ok:hover{background:#ecfdf5}
.col-reason{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logs-section{margin-bottom:16px}
.logs-section h4{font-size:13px;color:#333;margin:0 0 8px}
.modal-mask{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:100;display:flex;align-items:center;justify-content:center}
.modal{background:#fff;border-radius:10px;padding:20px 24px;min-width:320px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
.modal h4{margin:0 0 12px;font-size:15px;color:#333}
.modal-input{width:100%;border:1px solid #d0d0d4;border-radius:6px;padding:7px 10px;font-size:13px;margin-bottom:10px}
.modal-btns{display:flex;justify-content:flex-end;gap:8px}
.btn-sec{background:#fff;color:#555;border:1px solid #d0d0d4;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer}
</style>
