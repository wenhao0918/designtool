import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api'

function extractFilesFromContent(content: string): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  const re = /(?:^|[\s("'])(\S+\.(?:step|stl))/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    const fn = m[1].split('/').pop()!
    if (!seen.has(fn)) { seen.add(fn); result.push(fn) }
  }
  return result
}

export const useAppStore = defineStore('app', () => {
  const projects = ref<api.Project[]>([])
  const current = ref('')
  const phase = ref('')
  const messages = ref<api.Message[]>([])
  const docs = ref<Record<string, string[]>>({})
  const docOpen = ref(false)
  const docSection = ref('notes')
  const docFile = ref('')
  const rulesVisible = ref(false)
  const filesOpen = ref(false)
  const cadFiles = ref<string[]>([])
  const rulesContent = ref('')
  const busy = ref(false)
  const progress = ref('')
  const stepLogs = ref<string[]>([])
  const viewerOpen = ref(false)
  const viewerFile = ref('')
  const viewerNonce = ref(0)
const demoTarget = ref("")  // 侧栏选定要演示的项目  // 每次 openCadFile 递增:同一文件重复点击也强制触发加载
  const histPagesLeft = ref(0)  // 历史还有更早页可上翻(消息级分页)
  const showModal = ref(false)

  const currentProject = computed(() =>
    projects.value.find(p => p.project_id === current.value) || { project_id: current.value, name: current.value }
  )

  async function loadProjects() {
    // admin 角色传 all=true 可看所有用户项目
    const u = api.getUser()
    const isAdmin = u?.role === 'admin'
    // 项目身份统一为 projects.id(bigint);前端按不透明字符串透传(URL/localStorage/比较一致)
    const list = await api.getProjects(isAdmin)
    projects.value = (list || []).map((p: any) => ({
      ...p,
      project_id: String(p.project_id),
      parent: p.parent != null ? String(p.parent) : undefined,
    }))
    // 优先恢复上次使用的项目(持久化)
    const last = localStorage.getItem('anvil_last_project')
    if (!current.value && projects.value.length > 0) {
      const target = last && projects.value.some(p => p.project_id === last) ? last : projects.value[0].project_id
      await selectProject(target)
    }
  }

  async function deleteProject(id: string) {
    const proj = projects.value.find(p => p.project_id === id)
    const displayName = proj?.name || id
    if (!confirm(`确认删除项目 ${displayName}？`)) return
    await api.deleteProject(id)
    // 删除项目 = 整体删除:清理该项目的本地缓存(localStorage)
    localStorage.removeItem('anvil_last_project')
    localStorage.removeItem(`gantt_${id}`)
    if (current.value === id) {
      current.value = ''
      messages.value = []
      cadFiles.value = []
    }
    await loadProjects()
  }

  async function selectProject(id: string | number) {
    id = String(id)  // 统一字符串(bigint id 透传)
    // 设计进行中时点击当前项目:不重写 messages(否则进行中的 SSE 消息会被历史覆盖,
    // 表现为"切回来设计没了")。后端任务不受影响,继续跑。
    if (id === current.value && busy.value) return
    current.value = id
    localStorage.setItem('anvil_last_project', id)
    try {
    const [status, hpage, d] = await Promise.all([
      api.getProjectStatus(id),
      api.getHistoryPage(id, 1, 200, true),
      api.getDocs(id)
    ])
    const history = (hpage as any).messages || []
    histTotalPages.value = (hpage as any).total_pages || 1
    histPagesLeft.value = Math.max(0, (hpage as any).total_pages - 1)
    phase.value = status.phase || ''

    await loadCadFiles()

    const filtered = history || []
    messages.value = filtered.map((item: any) => {
        const content = typeof item.data?.content === 'string' ? item.data.content : JSON.stringify(item.data || '')
        const historyFiles = (item.data?.files || []) as string[]
        // 历史 files 可能是绝对路径(旧)或相对项目根路径(新,如 cad/{step_id}/design.step)。
        // 统一转成 cad 相对形式 step_id/file,与 /api/project/{id}/cad/ 返回的列表精确匹配,
        // 保证历史消息里的链接指向「当时」那轮的结果,而不是取最新同名文件。
        const validFiles = historyFiles.length
          ? historyFiles
              .map((f: string) => {
                const m = f.match(/(?:^|\/)cad\/(.+)$/)
                if (m) return m[1]
                return f.split('/').pop() || f
              })
              .filter((p: string) => cadFiles.value.includes(p))
          : undefined
        return {
          role: item.type as 'user' | 'assistant',
          content,
          timestamp: item.timestamp || '',
          files: validFiles && validFiles.length ? validFiles : undefined,
          tools_used: item.tools_used,
          seq_range: item.seq_range
        } as any
      })
    docs.value = d.docs || {}
    } catch(e) {
      console.error('selectProject error', e)
      messages.value = [{ role: 'assistant' as const, content: 'Error loading project: ' + String(e) }]
    }
    // 切换项目后恢复该项目的进行中/刚结束任务(切走再回来设计不丢)
    await restoreTaskState()
  }

  function toggleDocs() { docOpen.value = !docOpen.value; if (docOpen.value) { viewerOpen.value = false; filesOpen.value = false; rulesVisible.value = false } }
  function closeDocs() { docOpen.value = false }
  function toggleRules() { rulesVisible.value = !rulesVisible.value; if (rulesVisible.value) { viewerOpen.value = false; filesOpen.value = false; docOpen.value = false; loadRules() } }
  function closeRules() { rulesVisible.value = false }

  function toggleFiles() {
    filesOpen.value = !filesOpen.value
    if (filesOpen.value) { viewerOpen.value = false; rulesVisible.value = false; docOpen.value = false; loadCadFiles() }
  }
  function closeFiles() { filesOpen.value = false }

  async function loadCadFiles() {
    try {
      const r = await api.getCadFiles(current.value)
      cadFiles.value = r
    } catch { cadFiles.value = [] }
  }

  async function loadRules() {
    const r = await api.getRules(current.value)
    rulesContent.value = r.content || ''
  }

  async function doSaveRules() {
    await api.saveRules(current.value, rulesContent.value)
  }

  async function doCreateProject(name: string, description?: string, parent = '') {
    const r = await api.createProject(name, description, parent)
    await loadProjects()
    // r contains project_id from new API
    selectProject(r.project_id || name)
  }

  let abortController: AbortController | null = null

  // Retry 按钮 = 重新执行：撤销上一步设计并重放(服务端 9997 语义)，非重发原文
  function resendMsg(_text: string) { send('重新执行') }

  async function loadEarlierMessages() {
    if (!histPagesLeft.value || !current.value) return
    // 逐页向前 prepend(当前展示的是最后一页 page=total_pages)
    const d = await api.getHistoryPage(current.value, (histTotalPages.value - histPagesLeft.value) + 1, 200)
    const older = (d.messages || []).map((item: any) => ({
      role: item.type, content: typeof item.data?.content === 'string' ? item.data.content : JSON.stringify(item.data || ''),
      timestamp: item.timestamp || '',
      files: (item.data?.files || []).length ? item.data.files : undefined
    }))
    messages.value = [...older, ...messages.value]
    histPagesLeft.value = Math.max(0, histPagesLeft.value - 1)
  }
  const histTotalPages = ref(1)

  function openCadFile(f: string) {
    viewerFile.value = f  // 保留完整路径(step_dir/design.stl),Viewer3D 用它拼 URL
    viewerOpen.value = true
    viewerNonce.value++  // 同一文件重复点击也触发 watch 重新加载
    // 打开 3D/FC 时关闭其他面板,避免 tab 竞争
    filesOpen.value = false
    rulesVisible.value = false
    docOpen.value = false
  }

  function stopSend() {
    if (abortController) abortController.abort()
    busy.value = false
    progress.value = ''
  }

  function logout() {
    api.clearToken()
    window.location.reload()
  }

  async function send(text: string) {
    if (!text) return
    const ts = new Date().toISOString()
    const userMsg = { role: 'user', content: text, timestamp: ts } as any
    messages.value.push(userMsg)
    busy.value = true
    progress.value = 'Sending...'
    stepLogs.value = []
    // Insert placeholder assistant message for streaming updates
    // 注意:持有对象引用而非索引——selectProject() 可能整体重写 messages 数组,
    // 用索引会越界/写到别处。对象引用即使脱离数组也安全。
    const msg = { role: 'assistant', content: '', logs: [], files: [], timestamp: '' } as any
    messages.value.push(msg)
    abortController = new AbortController()
    // Snapshot existing cad files before this round
    let beforeFiles: string[] = []
    try { beforeFiles = await api.getCadFiles(current.value) } catch {}
    try {
      const r = await api.sendMessage(current.value, text, messages.value.slice(0, -1))
      const reader = r.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''  // SSE 跨 chunk 缓冲:一个 data 行可能被拆到多个 chunk
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''  // 最后一段可能是半行,留到下一个 chunk
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            try {
              const j = JSON.parse(data)
              if (j.type === 'token') {
                msg.content += j.content || ''
              } else if (j.type === 'progress') {
                progress.value = j.content
              } else if (j.type === 'step') {
                if (!msg.logs) msg.logs = []
                msg.logs!.push(j.content)
              } else if (j.type === 'file') {
                if (!msg.files) msg.files = []
                msg.files!.push(j.content)
              } else if (j.type === 'error') {
                if (j.code === 'MODEL_NOT_CONFIGURED') {
                  msg.content += '\n⚙️ ' + (j.content || '') + '\n（左侧栏「设置 → 模型配置」填入 API Key 保存后重试）'
                } else {
                  msg.content += '\n[Error: ' + j.content + ']'
                }
              }
            } catch { msg.content += data }
          }
        }
      }
      // 处理最后的残留(流结束时 buffer 里的完整行)
      if (buf.startsWith('data: ')) {
        try {
          const j = JSON.parse(buf.slice(6))
          if (j.type === 'token') msg.content += j.content || ''
        } catch {}
      }
      // Collect files: SSE events + content extraction + CAD diff, dedup by basename
      try {
        const list: string[] = await api.getCadFiles(current.value)
        cadFiles.value = list
        const newFiles = list.filter((f: string) => !beforeFiles.includes(f))
        // 保留 step 级相对路径({step_id}/file):每步结果独立,链接指向当轮;
        // basename 仅作去重键。sseFiles/newFiles 在前(step 感知优先于 content 提取的裸名)。
        const sseFiles = (msg.files || []).map((f: string) => f.replace(/^cad\//, ''))
        const contentFiles = extractFilesFromContent(msg.content)
        const seen = new Set<string>()
        const allFiles: string[] = []
        for (const f of [...sseFiles, ...contentFiles, ...newFiles]) {
          const norm = f.replace(/^cad\//, '')
          const bn = norm.split('/').pop() || norm
          if (!seen.has(bn)) { seen.add(bn); allFiles.push(norm) }
        }
        if (allFiles.length) {
          msg.files = allFiles
          // 新文件生成后只刷新文件列表(抽屉 📁 可见),不弹独立 FilesPanel
          // (避免浮层盖住抽屉、拦截 📐 等按钮点击)
        }
      } catch {}
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        msg.content = 'Error: ' + e.message
      }
    }
    busy.value = false
    progress.value = ''
    abortController = null
    // Stamp assistant completion time
    if (msg) {
      msg.timestamp = new Date().toISOString()
    }
    if (!msg.content && !msg.logs?.length) {
      const idx = messages.value.indexOf(msg)
      if (idx >= 0) messages.value.splice(idx, 1)
    }
  }

  // 恢复进行中的设计:查询后端任务注册表,若该轮任务还在跑/刚结束,补回消息与进度。
  // 前端任何时刻(页面加载、切回设计页)调用,保证"切换界面/刷新"不丢失设计现场。
  async function restoreTaskState() {
    if (!current.value) return
    try {
      const t = await api.getTaskStatus(current.value)
      if (!t || !t.started_at) return
      // 只在"没有任何进行中标记"且后端任务确实启动过时恢复,避免覆盖新的 send()
      if (busy.value) return
      const lastMsg = messages.value[messages.value.length - 1]
      if (lastMsg?.role === 'assistant' && lastMsg.content) return  // 已有完整结果,无需恢复
      if (t.busy) {
        // 任务仍在跑:补一条"进行中"占位,进度/日志从注册表取
        const restored = { role: 'assistant', content: t.content || '', logs: [...(t.step_logs || [])], files: [...(t.files || [])], timestamp: '', restored: true } as any
        // 避免重复插入:若最后一条是同一任务的占位,直接更新它
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'assistant' && ((last as any).restored || last.content === '')) {
          last.content = restored.content; last.logs = restored.logs; last.files = restored.files
        } else {
          messages.value.push(restored)
        }
        busy.value = true
        progress.value = t.progress || '设计进行中...'
        stepLogs.value = [...(t.step_logs || [])]
        cadFiles.value = [...(t.files || [])]
      } else if (t.content || t.error) {
        // 任务刚结束但前端错过了流:补上最终结果(不置 busy)
        const finalMsg = { role: 'assistant', content: t.content || (t.error ? '[Error: ' + t.error + ']' : ''), logs: [...(t.step_logs || [])], files: [...(t.files || [])], timestamp: t.finished_at || new Date().toISOString(), restored: true } as any
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'assistant' && ((last as any).restored || last.content === '')) {
          last.content = finalMsg.content; last.logs = finalMsg.logs; last.files = finalMsg.files; last.timestamp = finalMsg.timestamp
        } else {
          messages.value.push(finalMsg)
        }
        cadFiles.value = [...(t.files || [])]
      }
    } catch { /* 状态查询失败静默(后端可能未部署新接口) */ }
  }

  return {
    projects, current, phase, messages, docs,
    docOpen, docSection, docFile,
    filesOpen, cadFiles, toggleFiles, closeFiles, loadCadFiles, histPagesLeft, loadEarlierMessages, demoTarget,
    rulesVisible, rulesContent,
    busy, progress, stepLogs,
    viewerOpen, viewerFile, viewerNonce, showModal,
    currentProject,
    loadProjects, deleteProject, selectProject,
    toggleDocs, closeDocs,
    toggleRules, closeRules, loadRules, doSaveRules,
    doCreateProject, send, stopSend, resendMsg, openCadFile, restoreTaskState
  }
})
