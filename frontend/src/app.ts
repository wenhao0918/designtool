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
  const encoderMode = ref(false)
  const progress = ref('')
  const stepLogs = ref<string[]>([])
  const viewerOpen = ref(false)
  const viewerFile = ref('')
  const viewerNonce = ref(0)
const demoTarget = ref('')  // 侧栏选定要演示的项目
function _noopDemo() {}  // 每次 openCadFile 递增:同一文件重复点击也强制触发加载
  const histPagesLeft = ref(0)  // 历史还有更早页可上翻(消息级分页)
  const showModal = ref(false)

  const currentProject = computed(() =>
    projects.value.find(p => p.project_id === current.value) || { project_id: current.value, name: current.value }
  )

  async function loadProjects() {
    projects.value = await api.getProjects()
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

  async function selectProject(id: string) {
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

  async function doCreateProject(name: string, description?: string) {
    const r = await api.createProject(name, description)
    await loadProjects()
    // r contains project_id from new API
    selectProject(r.project_id || name)
  }

  let abortController: AbortController | null = null

  function resendMsg(text: string) { send(text) }

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
    if (encoderMode.value) return sendTranslate(text)
    const ts = new Date().toISOString()
    messages.value.push({ role: 'user', content: text, timestamp: ts })
    busy.value = true
    progress.value = 'Sending...'
    stepLogs.value = []
    // Insert placeholder assistant message for streaming updates
    const msgIdx = messages.value.length
    messages.value.push({ role: 'assistant', content: '', logs: [], files: [], timestamp: '' })
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
                messages.value[msgIdx].content += j.content || ''
              } else if (j.type === 'progress') {
                progress.value = j.content
              } else if (j.type === 'step') {
                if (!messages.value[msgIdx].logs) messages.value[msgIdx].logs = []
                messages.value[msgIdx].logs!.push(j.content)
              } else if (j.type === 'file') {
                if (!messages.value[msgIdx].files) messages.value[msgIdx].files = []
                messages.value[msgIdx].files!.push(j.content)
              } else if (j.type === 'error') {
                messages.value[msgIdx].content += '\n[Error: ' + j.content + ']'
              }
            } catch { messages.value[msgIdx].content += data }
          }
        }
      }
      // 处理最后的残留(流结束时 buffer 里的完整行)
      if (buf.startsWith('data: ')) {
        try {
          const j = JSON.parse(buf.slice(6))
          if (j.type === 'token') messages.value[msgIdx].content += j.content || ''
        } catch {}
      }
      // Collect files: SSE events + content extraction + CAD diff, dedup by basename
      try {
        const list: string[] = await api.getCadFiles(current.value)
        cadFiles.value = list
        const newFiles = list.filter((f: string) => !beforeFiles.includes(f))
        // 保留 step 级相对路径({step_id}/file):每步结果独立,链接指向当轮;
        // basename 仅作去重键。sseFiles/newFiles 在前(step 感知优先于 content 提取的裸名)。
        const sseFiles = (messages.value[msgIdx].files || []).map((f: string) => f.replace(/^cad\//, ''))
        const contentFiles = extractFilesFromContent(messages.value[msgIdx].content)
        const seen = new Set<string>()
        const allFiles: string[] = []
        for (const f of [...sseFiles, ...contentFiles, ...newFiles]) {
          const norm = f.replace(/^cad\//, '')
          const bn = norm.split('/').pop() || norm
          if (!seen.has(bn)) { seen.add(bn); allFiles.push(norm) }
        }
        if (allFiles.length) {
          messages.value[msgIdx].files = allFiles
          // 新文件生成后只刷新文件列表(抽屉 📁 可见),不弹独立 FilesPanel
          // (避免浮层盖住抽屉、拦截 📐 等按钮点击)
        }
      } catch {}
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        messages.value[msgIdx].content = 'Error: ' + e.message
      }
    }
    busy.value = false
    progress.value = ''
    abortController = null
    // Stamp assistant completion time
    if (messages.value[msgIdx]) {
      messages.value[msgIdx].timestamp = new Date().toISOString()
    }
    if (!messages.value[msgIdx].content && !messages.value[msgIdx].logs?.length) {
      messages.value.splice(msgIdx, 1)
    }
  }

  function toggleTranslator() {
    encoderMode.value = !encoderMode.value
  }

  async function sendTranslate(text: string) {
    const ts = new Date().toISOString()
    messages.value.push({ role: 'user', content: text, timestamp: ts })
    busy.value = true
    progress.value = '译码中...'
    try {
      const r = await api.translateDesign(current.value, text)
      if (r.error) {
        messages.value.push({ role: 'assistant', content: '❌ 译码失败: ' + r.error, logs: [], files: [], timestamp: new Date().toISOString() })
      } else {
        const steps = r.steps || []
        const content = `${r.echo}\n\n数字矩阵 ΔQ: [${r.dltq.join(', ')}]\n执行 ${steps.length} 步 (stub)`
        const logs = steps.map((s: any) => s.note || '')
        messages.value.push({ role: 'assistant', content, logs, files: [], timestamp: new Date().toISOString() })
      }
    } catch (e: any) {
      messages.value.push({ role: 'assistant', content: 'Error: ' + e.message, logs: [], files: [], timestamp: new Date().toISOString() })
    }
    busy.value = false
    progress.value = ''
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
    doCreateProject, send, stopSend, resendMsg, openCadFile,
    encoderMode, toggleTranslator
  }
})
