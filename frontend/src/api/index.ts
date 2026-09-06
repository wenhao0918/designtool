const TOKEN_KEY = "anvil_token"
const USER_KEY = "anvil_user"

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function setUser(user: { id: number; username: string; role: string }) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function getUser(): { id: number; username: string; role: string } | null {
  const raw = localStorage.getItem(USER_KEY)
  return raw ? JSON.parse(raw) : null
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  const h: Record<string, string> = {}
  if (token) h["Authorization"] = "Bearer " + token
  return h
}

export async function api<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const h = authHeaders()
  if (opts?.headers) {
    Object.assign(h, opts.headers)
  }
  const r = await fetch(path, { ...opts, headers: h })
  if (r.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error("Unauthorized")
  }
  return r.json()
}

export async function apiRaw(path: string, opts?: RequestInit): Promise<Response> {
  const h = authHeaders()
  if (opts?.headers) {
    Object.assign(h, opts.headers)
  }
  const r = await fetch(path, { ...opts, headers: h })
  if (r.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error("Unauthorized")
  }
  return r
}

export async function login(username: string, password: string): Promise<{ token: string; user: { id: number; username: string; role: string } }> {
  const r = await fetch("/admin-api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!r.ok) {
    let detail = "Login failed"
    try { const j = await r.json(); detail = j.detail || detail } catch {}
    throw new Error(detail + " (HTTP " + r.status + ")")
  }
  const data = await r.json()
  setToken(data.token)
  setUser(data.user)
  return data
}

export async function checkAuth(): Promise<boolean> {
  const token = getToken()
  if (!token) return false
  try {
    const r = await fetch("/admin-api/auth/me", { headers: { Authorization: "Bearer " + token } })
    if (!r.ok) { clearToken(); return false }
    return true
  } catch { clearToken(); return false }
}

export function logout() {
  clearToken()
  window.location.reload()
}

// === Existing API types ===
export interface Project {
  project_id: string
  name: string
  dir_name?: string
  phase?: string
  display?: string
  permission?: string  // read / comment / edit(共享项目)
  owner?: string       // 共享项目所有者用户名
  parent?: string      // 父项目 project_id(分级子项目)
}

export interface ProjectData {
  phase: string
  history: Message[]
  docs?: Record<string, string[]>
}

export interface Message {
  tools_used?: { tool: string; n: number }[]
  seq_range?: number[]
  role: "user" | "assistant"
  content: string
  timestamp?: string
  logs?: string[]
  files?: string[]
}

export interface DocTree {
  docs: Record<string, string[]>
}

// === Existing API functions (with auth headers) ===

export async function getProjects(all: boolean = false): Promise<Project[]> {
  const q = all ? "?all=true" : ""
  return api("/api/projects" + q)
}

export async function getProjectStatus(name: string): Promise<{ phase: string }> {
  return api("/api/project/" + name + "/status")
}

export async function getHistory(name: string): Promise<Message[]> {
  // 消息级分页取最后一页(后端已折叠 tool 流水);老 limit 协议不再使用。
  const d = await getHistoryPage(name, 1, 200, true)
  return d.messages as any
}

export interface HistoryPage {
  messages: any[]
  total_messages: number
  total_pages: number
  page: number
  size: number
}

export async function getHistoryPage(name: string, page: number, size = 50, last = false): Promise<HistoryPage> {
  // last=true → 请求第1页后跳到总页数(取最新一页;消息按时间正序展示)
  const d: HistoryPage = await api(`/api/project/${name}/history?page=${page}&size=${size}`)
  if (last && d.total_pages > 1) {
    return api(`/api/project/${name}/history?page=${d.total_pages}&size=${size}`)
  }
  return d
}

export async function getHistoryDetail(name: string, fromSeq: number, toSeq: number): Promise<{ rows: any[] }> {
  return api(`/api/project/${name}/history/detail?from_seq=${fromSeq}&to_seq=${toSeq}`)
}

export async function getDocs(name: string): Promise<DocTree> {
  return api("/api/project/" + name + "/docs")
}

export async function getDocContent(project: string, section: string, file: string): Promise<string> {
  const r = await apiRaw("/api/project/" + project + "/doc/" + section + "/" + file)
  return r.text()
}

export async function getRules(project: string): Promise<{ content: string }> {
  return api("/api/project/" + project + "/rules")
}

export async function saveRules(project: string, content: string): Promise<void> {
  await api("/api/project/" + project + "/rules", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content })
  })
}

export async function getGantt(project: string): Promise<{ content: string }> {
  return api("/api/project/" + project + "/gantt")
}

export async function saveGantt(project: string, data: string): Promise<void> {
  await api("/api/project/" + project + "/gantt", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data })
  })
}

export interface GanttFileInfo {
  project_id: string
  name: string
  dir_name: string
  updated: string
  task_count: number
}

export async function listGantt(): Promise<GanttFileInfo[]> {
  const r = await api("/api/gantt/list")
  return (r.files || []) as GanttFileInfo[]
}

// === Material (标准件库) 查询 ===
export interface MaterialListResp {
  total: number
  rows: any[]
  code?: number
  msg?: string
}

export async function materialList(
  collection: 'partCategory' | 'standardPart' | 'nonstandardPart' | 'industryPart' | 'enterprisePart' | 'supplierInfo' | 'searchCache',
  params: Record<string, string | number | undefined> = {}
): Promise<MaterialListResp> {
  const q = new URLSearchParams()
  Object.entries({ pageNum: 1, pageSize: 50, ...params }).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v) !== '') q.set(k, String(v))
  })
  return api(`/api/material/${collection}/list?${q.toString()}`)
}

export interface CreateResult {
  success: boolean
  project_id: string
  name: string
}

export async function createProject(name: string, description?: string, parent = ''): Promise<CreateResult> {
  return api("/api/projects/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description || "", parent_project: parent })
  })
}

export async function getPrimitives(): Promise<any> {
  return api("/api/primitives")
}

export async function sendMessage(project: string, message: string, history: Message[]): Promise<Response> {
  const h = authHeaders()
  h["Content-Type"] = "application/json"
  return fetch("/api/chat", {
    method: "POST",
    headers: h,
    body: JSON.stringify({ project, message, history })
  })
}

export async function translateDesign(project: string, message: string): Promise<any> {
  const h = authHeaders()
  h["Content-Type"] = "application/json"
  const r = await fetch("/api/translate", {
    method: "POST",
    headers: h,
    body: JSON.stringify({ project, message })
  })
  return r.json()
}

export interface TaskStatus {
  busy: boolean
  progress: string
  content: string
  files: string[]
  step_logs: string[]
  started_at: string | null
  finished_at: string | null
  error: string
}

export async function getTaskStatus(project: string): Promise<TaskStatus> {
  return api(`/api/project/${encodeURIComponent(project)}/task/status`)
}

export async function sketchApi(project: string, imageBlob: Blob, message?: string, scene?: string, llmConfig?: any): Promise<any> {
  const fd = new FormData()
  fd.append("project", project)
  fd.append("file", imageBlob, "sketch.png")
  if (message) fd.append("message", message)
  if (scene) fd.append("scene", scene)
  if (llmConfig) fd.append("llm_config", JSON.stringify(llmConfig))
  const r = await fetch("/api/sketch", {
    method: "POST",
    headers: authHeaders(),
    body: fd
  })
  if (r.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error("Unauthorized")
  }
  return r.json()
}

export async function downloadCadFile(name: string, filename: string): Promise<void> {
  // filename 可能是相对路径(如 step_dir/design.stl),分段编码,保留 /
  const enc = filename.split('/').map(encodeURIComponent).join('/')
  const r = await fetch("/api/project/" + encodeURIComponent(name) + "/cad/" + enc, {
    headers: authHeaders(),
  })
  if (!r.ok) throw new Error('下载失败: HTTP ' + r.status)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export async function getCadFiles(name: string): Promise<string[]> {
  const r = await fetch("/api/project/" + encodeURIComponent(name) + "/cad/", {
    headers: authHeaders(),
  })
  if (!r.ok) return []
  return r.json()
}

export async function drawingUrl(name: string, filename: string, fmt: 'svg' | 'pdf' = 'svg'): Promise<string> {
  // filename 形如 step_dir/design.step
  const enc = filename.split('/').map(encodeURIComponent).join('/')
  return "/api/project/" + encodeURIComponent(name) + "/cad/" + enc + "/drawing?fmt=" + fmt
}

export interface AdminLogs {
  downloads: { time: string; username: string; project: string; file: string; action: string; size: number }[]
  design: { seq: number; id: string; time: string; username: string; project: string; action: string; instruction: string; llm_response: string; output_dir: string }[]
}

export async function adminLogs(): Promise<AdminLogs> {
  return api("/admin-api/admin/logs")
}

export async function designLogRollback(project: string, seq: number): Promise<any> {
  return api("/api/project/" + encodeURIComponent(project) + "/design-log/rollback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seq }),
  })
}

export interface DesignLogEntry {
  seq: number
  dltq_seq?: number | null   // 指令序号 Δ#N(dltQ 账本,永不复用;非译码轮为空)
  id: string
  time: string
  action: string
  instruction: string
  llm_response: string
  output_dir: string
}

export async function designLog(project: string): Promise<DesignLogEntry[]> {
  return api("/api/project/" + encodeURIComponent(project) + "/design-log")
}

// === 机械设计术语表 ===
export interface MechTerm {
  id: number
  term: string
  definition: string
  geometry: string
  modeling: string
}

export async function listTerms(): Promise<MechTerm[]> {
  return api("/api/terms")
}
export async function createTerm(data: { term: string; definition?: string; geometry?: string; modeling?: string }): Promise<any> {
  return api("/api/terms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
}
export async function updateTerm(id: number, data: { term: string; definition?: string; geometry?: string; modeling?: string }): Promise<any> {
  return api("/api/terms/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
}
export async function deleteTerm(id: number): Promise<any> {
  return api("/api/terms/" + id, { method: "DELETE" })
}

// === 用户管理(admin) ===
export interface AdminUser {
  id: number
  username: string
  display_name: string
  role: string
  status: string
  is_test: boolean
  created_at: string
}
export interface LoginLogItem {
  id: number
  username: string
  success: boolean
  ip: string
  user_agent: string
  detail: string
  time: string
}

export async function adminUsers(): Promise<AdminUser[]> {
  return api("/admin-api/admin/users")
}
export async function adminCreateUser(data: { username: string; password: string; display_name?: string; role: string }): Promise<any> {
  return api("/admin-api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
}
export async function adminUpdateUser(id: number, data: { role?: string; status?: string; password?: string; display_name?: string; is_test?: boolean }): Promise<any> {
  return api("/admin-api/admin/users/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
}
export async function adminDeleteUser(id: number): Promise<any> {
  return api("/admin-api/admin/users/" + id, { method: "DELETE" })
}
export async function adminLoginLogs(): Promise<LoginLogItem[]> {
  return api("/admin-api/admin/login-logs")
}
export interface TokenUsageSummary { days: number; total_tokens: number; by_user: { username: string; prompt: number; completion: number; total: number; calls: number }[]; by_kind: { kind: string; prompt: number; completion: number; total: number; calls: number }[] }
export async function adminTokenUsage(days = 7): Promise<TokenUsageSummary> {
  return api("/admin-api/admin/token-usage?days=" + days)
}
export async function register(username: string, password: string, displayName?: string): Promise<any> {
  const r = await api<{ token: string; user: { id: number; username: string; role: string } }>("/admin-api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, display_name: displayName || "" })
  })
  // 注册接口返回 token+user(后端 create_token),立即保存进入登录态
  if (r?.token) {
    setToken(r.token)
    setUser(r.user)
  }
  return r
}
export async function changePassword(oldPassword: string, newPassword: string): Promise<any> {
  return api("/admin-api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
  })
}

// === 模型配置(用户自设 API key) ===
export interface ModelConfigItem { base_url: string; api_key: string; model: string }
export type ModelConfigs = Record<'inference' | 'vision' | 'voice', ModelConfigItem>

export async function getModelConfig(): Promise<ModelConfigs> {
  return api("/admin-api/settings/model-config")
}
export async function putModelConfig(cfg: ModelConfigs): Promise<any> {
  return api("/admin-api/settings/model-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg)
  })
}
export async function putModelConfigBatch(usernames: string[], cfg: { inference?: ModelConfigItem; vision?: ModelConfigItem; voice?: ModelConfigItem }): Promise<any> {
  return api("/admin-api/settings/model-config/batch", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usernames, ...cfg })
  })
}

// === 角色表(admin) ===
export interface RoleItem { code: string; name: string; description: string; permissions: string }
export async function adminRoles(): Promise<RoleItem[]> {
  return api("/admin-api/admin/roles")
}

// === 工具授权 ===
export interface ToolItem { code: string; name: string; description: string }
export async function myTools(): Promise<ToolItem[]> {
  const r = await api("/admin-api/auth/tools")
  return (r.tools || []) as ToolItem[]
}
export interface ToolAuthData {
  tools: ToolItem[]
  role_tools: { role_code: string; tool_code: string }[]
  user_tools: { user_id: number; tool_code: string; granted: number }[]
}
export async function adminTools(): Promise<ToolAuthData> {
  return api("/admin-api/admin/tools")
}
export async function setRoleTool(role_code: string, tool_code: string, granted: boolean): Promise<any> {
  return api("/admin-api/admin/tools/role", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role_code, tool_code, granted }) })
}
export async function setUserTool(user_id: number, tool_code: string, granted: boolean): Promise<any> {
  return api("/admin-api/admin/tools/user", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id, tool_code, granted }) })
}

// === 工具权限申请 ===
export interface PermissionRequestItem { id: number; username: string; tool_code: string; reason: string; status: string; created_at: string; reviewed_by?: string }
export async function myRequests(): Promise<PermissionRequestItem[]> {
  return api("/admin-api/requests")
}
export async function createPermissionRequest(tool_code: string, reason: string): Promise<any> {
  return api("/admin-api/requests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool_code, reason }) })
}
export async function adminRequests(status = "pending"): Promise<PermissionRequestItem[]> {
  return api("/admin-api/admin/requests?status=" + status)
}
export async function approveRequest(id: number): Promise<any> {
  return api("/admin-api/admin/requests/" + id + "/approve", { method: "POST" })
}
export async function rejectRequest(id: number): Promise<any> {
  return api("/admin-api/admin/requests/" + id + "/reject", { method: "POST" })
}

// === 数据共享 ===
export interface ShareItem { id: number; project_id: string; target_username: string; permission: string }
export async function listShares(): Promise<ShareItem[]> {
  return api("/api/shares")
}
export async function createShare(project_id: string, target_username: string, permission: string): Promise<any> {
  return api("/api/shares", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id, target_username, permission }) })
}
export async function deleteShare(id: number): Promise<any> {
  return api("/api/shares/" + id, { method: "DELETE" })
}

export async function deleteProject(name: string): Promise<void> {
  await fetch("/api/project/" + encodeURIComponent(name), {
    method: "DELETE",
    headers: authHeaders(),
  })
}
