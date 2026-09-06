<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import { useAppStore } from '@/stores/app'
import { downloadCadFile, getDocContent } from '@/api'

const store = useAppStore()
const container = ref<HTMLElement>()
const fcContainer = ref<HTMLElement>()
const partListEl = ref<HTMLElement>()
const infoEl = ref<HTMLElement>()

// 右侧抽屉:默认收起,宽度可拖拽调整,状态持久化(localStorage)
const sideCollapsed = ref(localStorage.getItem('anvil_viewer_side') !== 'open')
const sideWidth = ref(parseInt(localStorage.getItem('anvil_viewer_side_w') || '200', 10))
const sideTab = ref<DrawerTab>('3d')
const drawerTab = computed(() => sideTab.value)
const fcFileInput = ref<HTMLInputElement | null>(null)
const fcFileName = ref('')
const fcStatus = ref('')

// 3D 内嵌面板:默认收起(仅 ◀ 按钮),宽度可调,状态持久化
const panelOpen = ref(localStorage.getItem('anvil_viewer_panel') === 'open')
const panelWidth = ref(parseInt(localStorage.getItem('anvil_viewer_panel_w') || '520', 10))

// 统一抽屉 tab:3D / FreeCAD / 文件 / 规则 / 文档
const DRAWER_TABS = ['3d', 'freecad', 'files', 'rules', 'docs'] as const
type DrawerTab = typeof DRAWER_TABS[number]

// 面板状态跟随 store(任一打开 → 展开面板并切 tab)

// 加载项目内的 STEP 文件到 FreeCAD 容器(preview3d 端点)
async function loadProjectStep(relPath: string) {
  try {
    const proj = store.current
    const token = localStorage.getItem('anvil_token')
    const authH = token ? { Authorization: 'Bearer ' + token } : {}
    const previewUrl = `/api/project/${encodeURIComponent(proj)}/cad/${relPath.split('/').map(encodeURIComponent).join('/')}/preview3d`
    const resp = await fetch(previewUrl, { headers: authH })
    if (!resp.ok) throw new Error('加载失败 ' + resp.status)
    const vrmlText = await resp.text()
    if (vrmlText.startsWith('{') || vrmlText.startsWith('<')) throw new Error('转换失败: ' + vrmlText.slice(0, 80))
    fcStatus.value = '✅ 已加载'
    await renderVrml(vrmlText, 'STEP: ' + relPath.split('/').pop())
  } catch (e: any) {
    fcStatus.value = '❌ ' + (e.message || e)
  }
}

watch(() => store.filesOpen, (v) => { if (v) { panelOpen.value = true; sideTab.value = 'files' } })
watch(() => store.rulesVisible, (v) => { if (v) { panelOpen.value = true; sideTab.value = 'rules'; store.loadRules() } })
watch(() => store.docOpen, (v) => { if (v) { panelOpen.value = true; sideTab.value = 'docs' } })


// 文件窗口 FC 按钮:直接加载 STEP 到 FreeCAD 窗口
async function openFcFile(f: string) {
  sideTab.value = 'freecad'
  panelOpen.value = true
  localStorage.setItem('anvil_viewer_panel', 'open')
  store.filesOpen = false
  fcFileName.value = f.split('/').pop() || f
  fcStatus.value = '加载中...'
  await nextTick()
  await loadProjectStep(f)
}

// 工程图纸(STEP → 三视图 SVG,弹层显示)
const drawingOpen = ref(false)
const drawingSvg = ref('')
const drawingFile = ref('')
const drawingErr = ref('')
async function openDrawing(f: string) {
  drawingErr.value = ''
  drawingFile.value = f
  drawingOpen.value = true
  try {
    const enc = f.split('/').map(encodeURIComponent).join('/')
    const url = `/api/project/${encodeURIComponent(store.current)}/cad/${enc}/drawing?fmt=svg`
    const r = await fetch(url, { headers: { Authorization: 'Bearer ' + localStorage.getItem('anvil_token') } })
    if (!r.ok) {
      const t = await r.text()
      drawingErr.value = '图纸生成失败: ' + (t.slice(0, 120) || r.status)
      return
    }
    drawingSvg.value = await r.text()
  } catch (e: any) {
    drawingErr.value = '图纸生成失败: ' + (e?.message || e)
  }
}
async function downloadDrawingPdf() {
  const enc = drawingFile.value.split('/').map(encodeURIComponent).join('/')
  const url = `/api/project/${encodeURIComponent(store.current)}/cad/${enc}/drawing?fmt=pdf`
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + localStorage.getItem('anvil_token') } })
  if (!r.ok) { alert('PDF 生成失败: ' + r.status); return }
  const blob = await r.blob()
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u
  a.download = drawingFile.value.split('/').pop()!.replace('.step', '.pdf').replace('.stp', '.pdf')
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(u)
}

function togglePanel() {
  panelOpen.value = !panelOpen.value
  localStorage.setItem('anvil_viewer_panel', panelOpen.value ? 'open' : 'closed')
  if (panelOpen.value && container.value) nextTick(() => { /* ResizeObserver 自动适配 */ })
}

function selectTab(tab: DrawerTab) {
  sideTab.value = tab
  panelOpen.value = true
  localStorage.setItem('anvil_viewer_panel', 'open')
  // 切 tab 时同步 store 状态,避免 watch 竞争/残留
  store.viewerOpen = tab === '3d' || tab === 'freecad'
  // 文件已内嵌在抽屉 📁 tab 中;不再弹独立 FilesPanel(避免浮层盖住抽屉拦截点击)
  store.filesOpen = false
  store.rulesVisible = tab === 'rules'
  store.docOpen = tab === 'docs'
}

function onPanelResizeStart(e: PointerEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = panelWidth.value
  function onMove(ev: PointerEvent) {
    panelWidth.value = Math.min(900, Math.max(300, startW + (startX - ev.clientX)))
  }
  function onUp() {
    localStorage.setItem('anvil_viewer_panel_w', String(panelWidth.value))
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

// 文件窗口:按目录(step_dir)分组,目录名转可读时间
function parseStepDir(dir: string): { time: string; hash: string } {
  // 格式: {hash}_{YYYYMMDD_HHMMSS_mmm}
  const m = dir.match(/^([0-9a-f]{12})_(\d{8})_(\d{6})_(\d{3})$/)
  if (m) {
    const [, hash, d, t, ms] = m
    const time = `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)} ${t.slice(0,2)}:${t.slice(2,4)}:${t.slice(4,6)}.${ms}`
    return { time, hash }
  }
  return { time: dir, hash: '' }
}
const fileGroups = computed(() => {
  const map = new Map<string, { label: string; files: string[] }>()
  for (const f of store.cadFiles) {
    const parts = f.split('/')
    const dir = parts.length > 1 ? parts[0] : ''
    if (!map.has(dir)) {
      if (dir) {
        const { time, hash } = parseStepDir(dir)
        map.set(dir, { label: time + (hash ? ` #${hash}` : ''), files: [] })
      } else {
        // 根目录平铺文件 = 译码链当前产物(step_N/assembly)——置顶为「当前设计」
        map.set(dir, { label: '当前设计', files: [] })
      }
    }
    map.get(dir)!.files.push(f)
  }
  const groups = [...map.entries()].map(([dir, g]) => ({ dir, label: g.label, files: g.files }))
  // 当前设计置顶;历史目录按时间倒序(最新在上)
  groups.sort((a, b) => (a.dir === '' ? -1 : b.dir === '' ? 1 : b.dir.localeCompare(a.dir)))
  return groups
})

// 抽屉内文件下载 / 文档打开
async function downloadFile(f: string) {
  try { await downloadCadFile(store.current, f) } catch (e: any) { alert(e.message) }
}
async function openDoc(f: string) {
  try {
    const content = await getDocContent(store.current, store.docSection, f)
    alert(content.slice(0, 500) || '(空文档)')
  } catch (e: any) { alert('打开失败: ' + e.message) }
}

function onResizeStart(e: PointerEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = sideWidth.value
  function onMove(ev: PointerEvent) {
    const w = Math.min(420, Math.max(120, startW + (ev.clientX - startX)))
    sideWidth.value = w
  }
  function onUp() {
    localStorage.setItem('anvil_viewer_side_w', String(sideWidth.value))
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

watch(sideCollapsed, (v) => {
  localStorage.setItem('anvil_viewer_side', v ? 'closed' : 'open')
})

// ===== 统一视口工厂(全文件唯一场景/相机/renderer/controls/循环创建点) =====
// 铁律:一个容器同时只有一个 canvas、一条渲染循环。
// createViewport 重入时自动销毁该容器旧实例(rAF/controls/renderer/RO)。
const _vp: {
  el: HTMLElement | null; raf: number; renderer: any; controls: any; ro: any
  camera: any; scene: any; onFrame: (() => void) | null
} = { el: null, raf: 0, renderer: null, controls: null, ro: null, camera: null, scene: null, onFrame: null }

function destroyViewport() {
  if (_vp.raf) cancelAnimationFrame(_vp.raf)
  try { _vp.ro?.disconnect?.() } catch { /* ignore */ }
  try { _vp.controls?.dispose?.() } catch { /* ignore */ }
  try {
    if (_vp.renderer) {
      _vp.renderer.dispose?.()
      _vp.renderer.forceContextLoss?.()
      _vp.renderer.domElement?.remove?.()
    }
  } catch { /* ignore */ }
  _vp.raf = 0; _vp.renderer = null; _vp.controls = null; _vp.ro = null
  _3d.controls = null; _3d.camera = null
  _vp.el = null
}

async function createViewport(el: HTMLElement) {
  console.log('[vp] createViewport enter, el=', !!el)
  const THREE = await import('three')
  console.log('[vp] three imported')
  const { OrbitControls } = await import('three/addons/controls/OrbitControls.js')
  console.log('[vp] orbit imported')
  destroyViewport()
  _vp.el = el
  el.innerHTML = ''  // 清旧 canvas/overlay
  // 容器可能刚显示(v-show),等待非零尺寸
  let rect = el.getBoundingClientRect()
  if (rect.width < 10 || rect.height < 10) {
    await new Promise(r => setTimeout(r, 300))
    rect = el.getBoundingClientRect()
  }
  console.log('[vp] rect', rect.width, rect.height)
  const w = Math.round(rect.width) || 800, h = Math.round(rect.height) || 600

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x1a1a2e)
  const camera = new THREE.PerspectiveCamera(32, w / h, 1, 5000)
  camera.position.set(200, 150, 300)

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  // updateStyle=false:CSS 尺寸交给 style(100%)管,只设绘制缓冲区。
  // 默认 true 时 setSize 会改 canvas style → 触发容器 ResizeObserver →
  // 再 setSize → 布局反馈循环 = 画面持续闪动。
  renderer.setSize(w, h, false)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.2
  renderer.domElement.style.display = 'block'
  renderer.domElement.style.width = '100%'
  renderer.domElement.style.height = '100%'
  renderer.domElement.style.outline = 'none'
  el.appendChild(renderer.domElement)
  console.log('[vp] canvas appended', renderer.domElement.width, renderer.domElement.height)

  // v-show 切 tab 容器瞬时 0x0:非零防御,否则相机 aspect 被弄坏;
  // 只改缓冲区(updateStyle=false),杜绝 布局→观察→再布局 的闪动回路
  const ro = new ResizeObserver(() => {
    const r = el.getBoundingClientRect()
    if (r.width > 20 && r.height > 20) {
      renderer.setSize(Math.round(r.width), Math.round(r.height), false)
      camera.aspect = r.width / r.height
      camera.updateProjectionMatrix()
    }
  })
  ro.observe(el)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.enableZoom = true
  controls.zoomSpeed = 1.2
  controls.dampingFactor = 0.12

  // 灯光(一次配齐,所有视图共用)
  scene.add(new THREE.HemisphereLight(0x446688, 0x222244, 1.5))
  const key = new THREE.DirectionalLight(0xffeedd, 2.5); key.position.set(300, 400, 200); scene.add(key)
  const fill = new THREE.DirectionalLight(0x8899ff, 1.0); fill.position.set(-200, 100, -300); scene.add(fill)
  const rim = new THREE.DirectionalLight(0xffffff, 0.8); rim.position.set(0, -100, 200); scene.add(rim)
  scene.add(new THREE.GridHelper(800, 20, 0x444488, 0x333366))

  _vp.renderer = renderer; _vp.controls = controls; _vp.ro = ro
  _vp.camera = camera; _vp.scene = scene
  _3d.controls = controls; _3d.camera = camera

  // 常驻渲染循环(几何加载方无需再启停循环,天然杜绝双循环/僵尸循环)
  const tick = () => {
    _vp.raf = requestAnimationFrame(tick)
    controls.update()
    if (_vp.onFrame) { try { _vp.onFrame() } catch { /* ignore */ } }
    renderer.render(scene, camera)
  }
  tick()
  return { THREE, scene, camera, renderer, controls }
}

// 统一取景:包围盒自适应相机(近远裁剪面随模型尺寸,大模型不被裁小模型不闪)
function fitTo(THREE: any, obj: any, controls: any, camera: any, yOff = 0) {
  const box = new THREE.Box3().setFromObject(obj)
  const size = Math.max(box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z) || 1
  const cx = (box.max.x + box.min.x) / 2, cy = (box.max.y + box.min.y) / 2, cz = (box.max.z + box.min.z) / 2
  obj.position.set(obj.position.x - cx, obj.position.y - cy, obj.position.z - cz)  // 平移使包围盒中心到原点
  camera.near = Math.max(0.1, size * 0.002)
  camera.far = size * 50
  camera.updateProjectionMatrix()
  camera.position.set(size * 0.7, size * (0.8 + yOff), size * 1.3)
  controls.target.set(0, size * yOff * 0.3, 0)
  controls.update()
}

// 通用:VRML 文本渲染(FreeCAD tab / 本地 STEP 导入)—— 只建几何,视口走工厂
async function renderVrml(vrmlText: string, title: string) {
  const el = fcContainer.value
  if (!el) return
  const { THREE, scene, controls, camera } = await createViewport(el)
  const { VRMLLoader } = await import('three/addons/loaders/VRMLLoader.js')
  const obj = new VRMLLoader().parse(vrmlText, 'preview.wrl')
  scene.add(obj)
  _3d.rootGroup = obj
  fitTo(THREE, obj, controls, camera)
  if (partListEl.value) partListEl.value.innerHTML = '<div style="padding:16px;color:#888;font-size:12px">' + title + '</div>'
  document.querySelectorAll('.vloader-done, .viewer-loading').forEach(x => x.remove())
}

// FreeCAD tab:导入本地 STEP 文件查看
async function onFcFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  fcFileName.value = file.name
  fcStatus.value = '转换中...'
  try {
    const fd = new FormData()
    fd.append('file', file, file.name)
    const proj = store.current
    const token = localStorage.getItem('anvil_token')
    const authH = token ? { Authorization: 'Bearer ' + token } : {}
    const resp = await fetch(`/api/project/${encodeURIComponent(proj)}/preview-step`, { method: 'POST', headers: authH, body: fd })
    if (!resp.ok) throw new Error('转换失败 ' + resp.status)
    const vrmlText = await resp.text()
    if (vrmlText.startsWith('{') || vrmlText.startsWith('<')) throw new Error('转换失败: ' + vrmlText.slice(0, 80))
    fcStatus.value = '✅ 已加载'
    await renderVrml(vrmlText, 'FreeCAD 导入: ' + file.name)
  } catch (err: any) {
    fcStatus.value = '❌ ' + (err.message || err)
  }
  input.value = ''
}

interface PartManifest {
  name: string
  stl: string
  bounds?: number[]
}

const _3d = {
  rotating: false, xray: false, allParts: [] as any[], partMap: {} as Record<number, any>,
  hidden: {} as Record<number, boolean>, selected: null as any, hovered: null as any,
  manifest: null as PartManifest[] | null, controls: null as any, camera: null as any,
  palette: [0x4f8fff, 0x44cc88, 0xff7744, 0xbb66ee, 0x33bbdd, 0xff5566, 0x88cc33, 0xff9933, 0x66aaaa, 0xcc77aa],
  loadingEl: null as HTMLElement | null,
  rootGroup: null as any,
}

async function openViewer() {
  console.log('[vp] openViewer, file=', store.viewerFile)
  if (!store.viewerFile) return
  document.querySelectorAll('.anvil-tooltip').forEach(el => el.remove())
  await nextTick()
  const el = container.value
  if (!el) return

  // loading overlay(工厂会清容器,overlay 先记变量,加载文案由其显示)
  const loadingEl = document.createElement('div')
  loadingEl.className = 'viewer-loading'
  loadingEl.innerHTML = '<div class="vloader-spin"></div><div class="vloader-text">加载3D模型中...</div>'
  function showLoading(text: string) {
    loadingEl.remove()  // 旧 overlay 立即清除(绝不残留 DOM 拦截事件)
    loadingEl.className = 'viewer-loading'
    loadingEl.innerHTML = '<div class="vloader-spin"></div><div class="vloader-text"></div>'
    const t = loadingEl.querySelector('.vloader-text')
    if (t) t.textContent = text
    el.appendChild(loadingEl)
  }
  function hideLoading() {
    // 关键:立即从 DOM 移除。旧实现只加 vloader-done 类(视觉淡出),
    // 元素仍铺在 canvas 上(z-index:50 + pointer-events:auto)→ 永久拦截
    // 全部鼠标事件 → 拖不动/转不动(角度显示冻结)。
    loadingEl.remove()
  }
  showLoading('初始化视口...')

  try {
    // ===== 唯一视口创建点(工厂):场景/相机/灯/网格/循环 =====
    const { THREE, scene, camera, renderer, controls } = await createViewport(el)
    ;(window as any).__THREE_REF__ = THREE
    const { STLLoader } = await import('three/addons/loaders/STLLoader.js')

    // 坐标轴(仅 STL 装配视口)
    const axisLen = 300
    function makeTextSprite(text: string, color: string) {
      const cnv = document.createElement('canvas')
      cnv.width = 128; cnv.height = 64
      const ctx = cnv.getContext('2d')!
      ctx.font = 'bold 36px monospace'; ctx.fillStyle = color
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillText(text, 64, 32)
      const tex = new THREE.CanvasTexture(cnv)
      tex.minFilter = THREE.LinearFilter
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, depthWrite: false }))
      sp.scale.set(60, 30, 1)
      return sp
    }
    const axesGroup = new THREE.Group()
    for (const [v, c] of [[new THREE.Vector3(1,0,0), 0xff4444], [new THREE.Vector3(0,1,0), 0x44ff44], [new THREE.Vector3(0,0,1), 0x4488ff]] as any) {
      axesGroup.add(new THREE.ArrowHelper(v, new THREE.Vector3(0, 0, 0), axisLen, c, 12, 8))
    }
    const lx = makeTextSprite('+X', '#ff6666'); lx.position.set(axisLen + 35, 0, 0); axesGroup.add(lx)
    const ly = makeTextSprite('+Y', '#66ff66'); ly.position.set(0, axisLen + 35, 0); axesGroup.add(ly)
    const lz = makeTextSprite('+Z', '#6699ff'); lz.position.set(0, 0, axisLen + 35); axesGroup.add(lz)
    const nx = makeTextSprite('-X', '#994444'); nx.position.set(-axisLen - 35, 0, 0); axesGroup.add(nx)
    const ny = makeTextSprite('-Y', '#449944'); ny.position.set(0, -axisLen - 35, 0); axesGroup.add(ny)
    const nz = makeTextSprite('-Z', '#446699'); nz.position.set(0, 0, -axisLen - 35); axesGroup.add(nz)
    scene.add(axesGroup)

    // 角度显示挂工厂常驻循环
    _vp.onFrame = () => {
      const dx = camera.position.x - controls.target.x
      const dy = camera.position.y - controls.target.y
      const dz = camera.position.z - controls.target.z
      const azimuth = ((Math.atan2(dx, dz) * 180 / Math.PI) % 360 + 360) % 360
      const horiz = Math.sqrt(dx * dx + dz * dz)
      const polar = Math.atan2(dy, horiz) * 180 / Math.PI
      const aEl = document.getElementById('v-azimuth')
      const pEl = document.getElementById('v-polar')
      if (aEl) aEl.textContent = azimuth.toFixed(0) + '°'
      if (pEl) pEl.textContent = polar.toFixed(1) + '°'
    }

    // 通用:带鉴权 STL 拉取解析
    async function loadStl(path: string): Promise<any> {
      const resp = await fetch(path, { headers: authHeaders() })
      if (!resp.ok) throw new Error(path.split('/').pop() + ': HTTP ' + resp.status)
      if ((resp.headers.get('content-type') || '').includes('json')) throw new Error('Server returned JSON, not a 3D file')
      const buf = await resp.arrayBuffer()
      if (buf.byteLength < 84) throw new Error('File too small for STL')
      return new STLLoader().parse(buf)
    }

    const proj = store.current
    const stlFile = store.viewerFile
    const baseUrl = `/api/project/${encodeURIComponent(proj)}/cad`
    const fileUrl = (rel: string) => `${baseUrl}/${rel.split('/').map(encodeURIComponent).join('/')}`

    // ===== 路径一:STEP → OCP 转 VRML(复用主视口,只加载几何) =====
    if (/\.(step|stp)$/i.test(stlFile)) {
      showLoading('加载 STEP(内嵌转换)...')
      try {
        const { VRMLLoader } = await import('three/addons/loaders/VRMLLoader.js')
        const resp = await fetch(fileUrl(stlFile) + '/preview3d', { headers: authHeaders() })
        if (!resp.ok) throw new Error('preview3d HTTP ' + resp.status)
        const obj = new VRMLLoader().parse(await resp.text(), 'preview.wrl')
        scene.add(obj)
        _3d.rootGroup = obj
        fitTo(THREE, obj, controls, camera)
        if (partListEl.value) partListEl.value.innerHTML = '<div style="padding:16px;color:#888;font-size:12px">STEP 内嵌预览(OpenCascade 转换)</div>'
      } catch (e: any) {
        el.innerHTML = '<div style="text-align:center;padding:60px;color:#f55">STEP 预览失败: ' + (e.message || e) + '</div>'
        return
      }
      hideLoading()
      return
    }

    // ===== 路径二:STL 装配(manifest 逐件加载,带交互) =====
    const tooltip = document.createElement('div')
    tooltip.className = 'anvil-tooltip'
    document.body.appendChild(tooltip)
    const raycaster = new THREE.Raycaster()
    const mouse = new THREE.Vector2()

    try {
      showLoading('加载装配清单...')
      const resp = await fetch(fileUrl('manifest.json'), { headers: authHeaders() })
      if (!resp.ok) throw new Error('no manifest')
      const manifestData = await resp.json()
      if (!Array.isArray(manifestData) || !manifestData.length) throw new Error('no manifest')
      const manifest: PartManifest[] = manifestData
      _3d.manifest = manifest
      _3d.hidden = {}; _3d.partMap = {}; _3d.allParts = []
      const group = new THREE.Group()
      _3d.rootGroup = group
      scene.add(group)
      const allParts: any[] = []

      function buildPartList() {
        if (!partListEl.value) return
        partListEl.value.innerHTML = ''
        manifest.forEach((p, i) => {
          const item = document.createElement('div')
          item.className = 'part-item' + (_3d.hidden[i] ? ' hidden' : '') + (_3d.selected?.userData.idx === i ? ' sel' : '')
          const c = _3d.palette[i % _3d.palette.length].toString(16).padStart(6, '0')
          item.innerHTML = `<span class="dot" style="background:#${c}"></span><span class="name">${p.name || 'Part ' + (i + 1)}</span><button class="hide-btn" title="显示/隐藏零件" data-idx="${i}">${_3d.hidden[i] ? '\u25c9' : '\u25ce'}</button>`
          item.querySelector('.hide-btn')!.addEventListener('click', (e) => { e.stopPropagation(); togglePart(i) })
          item.addEventListener('click', () => focusPart(i))
          partListEl.value!.appendChild(item)
        })
      }
      function togglePart(idx: number) {
        _3d.hidden[idx] = !_3d.hidden[idx]
        if (_3d.partMap[idx]) _3d.partMap[idx].visible = !_3d.hidden[idx]
        buildPartList()
      }
      function focusPart(idx: number) {
        if (!_3d.partMap[idx]) return
        _3d.selected = _3d.partMap[idx]
        buildPartList()
        fitTo((window as any).__THREE_REF__, _3d.selected, controls, camera)
        if (infoEl.value) {
          const box = new THREE.Box3().setFromObject(_3d.selected)
          const s = Math.max(box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z) || 1
          infoEl.value.innerHTML = `<b>${manifest[idx].name}</b><br>Size: ${s.toFixed(1)}mm`
          infoEl.value.style.display = 'block'
        }
      }

      for (let idx = 0; idx < manifest.length; idx++) {
        const part = manifest[idx]
        showLoading(`加载 ${part.name || 'Part ' + (idx + 1)}... (${idx + 1}/${manifest.length})`)
        try {
          const geom = await loadStl(fileUrl(part.stl))
          geom.computeVertexNormals()
          geom.rotateX(-Math.PI / 2)  // FreeCAD Z-up → Three.js Y-up
          const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
            color: _3d.palette[idx % _3d.palette.length], metalness: 0.3, roughness: 0.6 }))
          mesh.userData = { partName: part.name, idx }
          group.add(mesh)
          _3d.partMap[idx] = mesh
          allParts.push(mesh)
          _3d.allParts = allParts
          group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geom),
            new THREE.LineBasicMaterial({ color: 0x88aaff, transparent: true, opacity: 0.25 })))
        } catch (e) {
          console.error('load failed:', part.stl, e)
        }
      }
      if (allParts.length) fitTo(THREE, group, controls, camera, 0.1)
      buildPartList()
      hideLoading()

      renderer.domElement.addEventListener('mousemove', (ev) => {
        if (!allParts.length) return
        const r = renderer.domElement.getBoundingClientRect()
        mouse.x = ((ev.clientX - r.left) / r.width) * 2 - 1
        mouse.y = -((ev.clientY - r.top) / r.height) * 2 + 1
        raycaster.setFromCamera(mouse, camera)
        const hits = raycaster.intersectObjects(allParts.filter(p => p.visible))
        if (hits.length) {
          const h: any = hits[0].object
          if (_3d.hovered && _3d.hovered !== h && _3d.hovered !== _3d.selected) _3d.hovered.material.emissive.setHex(0)
          _3d.hovered = h
          if (h !== _3d.selected) h.material.emissive.setHex(0x442200)
          tooltip.textContent = h.userData.partName || 'Part'
          tooltip.style.display = 'block'
          tooltip.style.left = (ev.clientX + 14) + 'px'
          tooltip.style.top = (ev.clientY - 28) + 'px'
          renderer.domElement.style.cursor = 'pointer'
        } else {
          if (_3d.hovered && _3d.hovered !== _3d.selected) _3d.hovered.material.emissive.setHex(0)
          _3d.hovered = null
          tooltip.style.display = 'none'
          renderer.domElement.style.cursor = 'default'
        }
      })
      renderer.domElement.addEventListener('click', () => { if (_3d.hovered) focusPart(_3d.hovered.userData.idx) })
    } catch (manifestErr) {
      // ===== 路径三:无 manifest → 单体 STL =====
      console.warn('manifest miss, fallback combined:', manifestErr)
      showLoading('加载STL模型...')
      try {
        const geom = await loadStl(fileUrl(stlFile))
        geom.computeVertexNormals()
        geom.rotateX(-Math.PI / 2)
        const g = new THREE.Group()
        _3d.rootGroup = g
        g.add(new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color: 0x4f8fff, metalness: 0.3, roughness: 0.6 })))
        scene.add(g)
        fitTo(THREE, g, controls, camera, 0.1)
        if (partListEl.value) partListEl.value.innerHTML = '<div style="padding:20px;text-align:center;color:#666;font-size:12px">Combined model</div>'
        hideLoading()
      } catch (stlErr: any) {
        el.innerHTML = '<div style="text-align:center;padding:60px;color:#f55">加载 3D 模型失败: ' + (stlErr.message || stlErr) + '</div>'
      }
    }
  } catch (e) {
    console.error('viewer error:', e)
    el.innerHTML = '<div style="text-align:center;padding:60px;color:#f55">Error: ' + e + '</div>'
  }
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('anvil_token')
  return token ? { Authorization: 'Bearer ' + token } : {}
}

// watch viewerOpen/viewerFile/viewerNonce:抽屉已开(viewerOpen 已 true)时再次点 3D 链接,
// viewerFile 不变则靠 viewerNonce(每次 openCadFile 递增)强制触发,保证切页+重新加载。
watch([() => store.viewerOpen, () => store.viewerFile, () => store.viewerNonce], ([open]) => {
  if (open) {
    panelOpen.value = true
    localStorage.setItem('anvil_viewer_panel', 'open')
    const f = store.viewerFile || ''
    if (/\\.(step|stp)$/i.test(f)) {
      // STEP → FreeCAD tab 自动加载(先切 tab 等 DOM 就绪,避免渲染到隐藏容器)
      sideTab.value = 'freecad'
      fcFileName.value = f.split('/').pop() || f
      fcStatus.value = '加载中...'
      nextTick(() => loadProjectStep(f))
    } else if (f) {
      // STL → 3D tab
      sideTab.value = '3d'
      openViewer()
    }
  }
})

function doToggleAutoRotate() {
  _3d.rotating = !_3d.rotating
  if (_3d.controls) { _3d.controls.autoRotate = _3d.rotating; _3d.controls.autoRotateSpeed = 2.0 }
  const b = document.getElementById('btnRotate'); if (b) b.classList.toggle('on')
}

function doResetView() {
  if (_3d.controls) _3d.controls.target.set(0, 0, 0)
  if (_3d.camera) { _3d.camera.position.set(200, 150, 300); _3d.camera.updateProjectionMatrix() }
  if (_3d.controls) _3d.controls.update()
}

function doFitView() {
  if (!_3d.rootGroup || !_3d.controls) return
  const THREE = (window as any).__THREE_REF__
  if (!THREE) return doResetView()
  try {
    const box = new THREE.Box3().setFromObject(_3d.rootGroup)
    const cx = (box.max.x + box.min.x) / 2, cy = (box.max.y + box.min.y) / 2, cz = (box.max.z + box.min.z) / 2
    const s = Math.max(box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z) || 1
    _3d.controls.target.set(cx, cy, cz)
    if (_3d.camera) {
      _3d.camera.position.set(cx + s * 0.6, cy + s * 0.8, cz + s * 1.2)
      _3d.camera.updateProjectionMatrix()
    }
    _3d.controls.update()
  } catch { doResetView() }
}

function doToggleXray() {
  _3d.xray = !_3d.xray
  _3d.allParts.forEach(p => {
    p.material.transparent = _3d.xray
    p.material.opacity = _3d.xray ? 0.35 : 1.0
    p.material.depthWrite = !_3d.xray
    p.material.needsUpdate = true
  })
  const b = document.getElementById('btnXray'); if (b) b.classList.toggle('on')
}
</script>

<template>
  <!-- 右侧抽屉:展开显示 tab 头+内容;收起只留一个右缘悬浮按钮 -->
  <div class="viewer-wrap" :class="{ collapsed: !panelOpen }" :style="{ width: panelOpen ? panelWidth + 'px' : '0px' }">
    <div class="side-resizer" v-show="panelOpen" @pointerdown="onPanelResizeStart"></div>
    <!-- 面板头:多 tab + 折叠按钮(收起时整体隐藏) -->
    <div v-show="panelOpen" class="viewer-hd">
      <div class="side-tabs">
        <button class="side-tab" :class="{ active: sideTab === '3d' }" @click="selectTab('3d')" title="3D 视图">3D</button>
        <button class="side-tab" :class="{ active: sideTab === 'freecad' }" @click="selectTab('freecad')" title="FreeCAD 视图(导入 STEP)">FreeCAD</button>
        <button class="side-tab" :class="{ active: sideTab === 'files' }" @click="selectTab('files')" title="生成文件">📁</button>
        <button class="side-tab" :class="{ active: sideTab === 'rules' }" @click="selectTab('rules')" title="设计规则">📝</button>
        <button class="side-tab" :class="{ active: sideTab === 'docs' }" @click="selectTab('docs')" title="项目文档">📚</button>
      </div>
      <button class="panel-toggle" :title="panelOpen ? '折叠面板' : '展开面板'" @click="togglePanel">{{ panelOpen ? '▷' : '◁' }}</button>
    </div>
    <!-- 内容区(折叠时隐藏):每个 tab 是独立子窗口 -->
    <div v-show="panelOpen" class="viewer-body">
      <!-- 3D 窗口 -->
      <div v-show="sideTab === '3d'" class="viewer-win">
        <div ref="container" class="viewer-canvas"></div>
        <div class="viewer-side" :class="{ collapsed: sideCollapsed }" :style="{ width: sideCollapsed ? '0px' : sideWidth + 'px' }">
          <h4>Parts</h4>
          <div class="part-list" ref="partListEl"></div>
          <div class="angle-display" id="angleDisplay">
            <div class="angle-row"><span class="angle-label">⤻ 方位</span><span class="angle-val" id="v-azimuth">0°</span></div>
            <div class="angle-row"><span class="angle-label">↕ 仰角</span><span class="angle-val" id="v-polar">0°</span></div>
          </div>
          <div class="viewer-tools">
            <button @click="doToggleAutoRotate" id="btnRotate" title="自动旋转">⟳ 旋转</button>
            <button @click="doFitView" title="自适应视图">⌖ 适应</button>
            <button @click="doResetView" title="复位到原点">⟲ 复位</button>
            <button @click="doToggleXray" id="btnXray" title="半透明模式">◈ 透视</button>
          </div>
        </div>
        <button class="side-toggle" @click="sideCollapsed = !sideCollapsed" :title="sideCollapsed ? '展开零件面板' : '收起零件面板'">
          {{ sideCollapsed ? '◀' : '▶' }}
        </button>
      </div>

      <!-- FreeCAD 窗口 -->
      <div v-show="sideTab === 'freecad'" class="viewer-win">
        <div ref="fcContainer" class="viewer-canvas"></div>
        <!-- 顶部小工具条 -->
        <div class="fc-toolbar">
          <button class="fc-btn-sm" @click="fcFileInput?.click()" title="导入本地 STEP 文件">📂 导入</button>
          <input ref="fcFileInput" type="file" accept=".step,.stp" style="display:none" @change="onFcFilePicked" />
          <span v-if="fcFileName" class="fc-file-sm" :title="fcFileName">{{ fcFileName }}</span>
          <span v-if="fcStatus" class="fc-status-sm" :class="{ err: fcStatus.startsWith('❌') }">{{ fcStatus }}</span>
        </div>
      </div>

      <!-- 文件窗口 -->
      <div v-show="sideTab === 'files'" class="viewer-win drawer-content">
        <div class="drawer-hd">
          <h4>📁 生成文件</h4>
          <span class="drawer-sub">{{ store.cadFiles.length }} files</span>
          <button class="drawer-refresh" @click="store.loadCadFiles()" title="刷新文件列表">⟳</button>
        </div>
        <div class="drawer-list">
          <div v-if="!store.cadFiles.length" class="drawer-empty">暂无生成文件<br /><small>让 AI 构建模型后,STEP/STL 文件会出现在这里</small></div>
          <div v-for="g in fileGroups" :key="g.dir" class="file-group">
            <div class="file-group-hd" :title="g.dir">
              <span class="file-group-time">🕐 {{ g.label }}</span>
              <span class="file-group-count">{{ g.files.length }} 文件</span>
            </div>
            <div v-for="f in g.files" :key="f" class="drawer-item">
              <span class="drawer-type">{{ f.endsWith('.step') ? 'STEP' : f.endsWith('.stl') ? 'STL' : (f.split('.').pop() || '').toUpperCase() }}</span>
              <span class="drawer-name" :title="f">{{ f.split('/').pop() }}</span>
              <span class="drawer-actions">
                <button v-if="f.endsWith('.stl')" class="mini" title="3D 查看" @click="store.openCadFile(f)">3D</button>
                <button v-if="f.match(/\.(step|stp)$/i)" class="mini" title="FreeCAD 查看" @click="openFcFile(f)">FC</button>
                <button v-if="f.match(/\.(step|stp)$/i)" class="mini" title="工程图纸(三视图)" @click="openDrawing(f)">📐</button>
                <button class="mini" title="下载" @click="downloadFile(f)">⬇</button>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 规则窗口 -->
      <div v-show="sideTab === 'rules'" class="viewer-win drawer-content">
        <div class="drawer-hd">
          <h4>📝 设计规则</h4>
          <span class="drawer-sub">注入为优先提示词</span>
          <button class="drawer-refresh" @click="store.doSaveRules()" title="保存规则">💾</button>
        </div>
        <textarea class="drawer-textarea" :value="store.rulesContent" @input="store.rulesContent = ($event.target as HTMLTextAreaElement).value"
          placeholder="输入设计规则,将注入到 AI 提示词..."></textarea>
      </div>

      <!-- 文档窗口 -->
      <div v-show="sideTab === 'docs'" class="viewer-win drawer-content">
        <div class="drawer-hd">
          <h4>📚 项目文档</h4>
          <span class="drawer-sub">{{ store.docSection }}</span>
          <button class="drawer-refresh" @click="store.selectProject(store.current)" title="刷新文档">⟳</button>
        </div>
        <div class="drawer-doc">
          <div v-for="f in (store.docs[store.docSection] || [])" :key="f" class="drawer-item" @click="openDoc(f)">
            <span class="drawer-name">{{ f.replace(/\.md$/, '').replace(/^\d{8}_\d{6}_/, '').replace(/_/g, ' ') }}</span>
          </div>
          <div v-if="!(store.docs[store.docSection] || []).length" class="drawer-empty">暂无文档</div>
        </div>
      </div>

      <div ref="infoEl" class="viewer-info"></div>
    </div>
    <!-- 收起态:右缘悬浮展开按钮 -->
    <button v-show="!panelOpen" class="drawer-open-btn" @click="togglePanel" title="展开侧边抽屉">◀</button>

    <!-- 工程图纸弹层 -->
    <div v-if="drawingOpen" class="drawing-mask" @click.self="drawingOpen = false">
      <div class="drawing-modal">
        <div class="drawing-hd">
          <h3>📐 工程图纸 <span class="drawing-file">{{ drawingFile }}</span></h3>
          <button class="drawing-pdf" @click="downloadDrawingPdf" title="下载 PDF">⬇ PDF</button>
          <button class="drawing-close" @click="drawingOpen = false">×</button>
        </div>
        <div v-if="drawingErr" class="drawing-err">{{ drawingErr }}</div>
        <div v-else-if="!drawingSvg" class="drawing-loading">图纸生成中...</div>
        <div v-else class="drawing-body" v-html="drawingSvg"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 右侧抽屉:展开显示面板;收起宽度0+全隐藏,只留右缘悬浮按钮 */
.viewer-wrap{
  position:absolute; top:48px; right:0; bottom:0; z-index:100;
  width:520px; background:#1a1a2e; border-left:1px solid #2a2a4e;
  display:flex; flex-direction:column;
  box-shadow:-4px 0 16px rgba(0,0,0,.25);
  transition:width .25s ease;
}
.viewer-wrap.collapsed{
  width:0 !important; border-left:none; box-shadow:none; overflow:visible;
}
.viewer-wrap.collapsed .viewer-hd{display:none}
.viewer-wrap.collapsed .viewer-body{display:none}
.viewer-wrap.collapsed .side-resizer{display:none}
/* 收起态:右缘悬浮展开按钮(wrap 宽0时其左缘=屏幕右缘,按钮 left:-24 贴屏幕右缘内侧) */
.drawer-open-btn{
  position:absolute; top:60px; left:-24px; z-index:30;
  background:#16213e; color:#aaa; border:1px solid #2a2a4e;
  border-radius:8px 0 0 8px; cursor:pointer; font-size:13px; padding:12px 5px;
}
.drawer-open-btn:hover{color:#fff;background:#4f46e5}
.side-resizer{
  position:absolute; top:0; bottom:0; left:0; width:6px;
  cursor:col-resize; z-index:10; transition:background .15s;
}
.side-resizer:hover,.side-resizer:active{background:rgba(74,125,255,.3)}
.viewer-hd{display:flex;align-items:center;padding:0;background:#16213e;flex-shrink:0;border-bottom:1px solid #2a2a4e}
.side-tabs{display:flex;flex-wrap:wrap;gap:2px;padding:6px 6px 6px 8px;flex:1;min-width:0}
.side-tab{
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:#aaa;
  padding:5px 7px;border-radius:5px;font-size:11px;cursor:pointer;white-space:nowrap;
}
.side-tab:hover{background:rgba(255,255,255,.12);color:#fff}
.side-tab.active{background:#4f46e5;border-color:#4f46e5;color:#fff;font-weight:600}
.panel-toggle{
  background:none;border:none;color:#888;cursor:pointer;font-size:13px;
  padding:8px 10px;flex-shrink:0;
}
.panel-toggle:hover{color:#fff}
.viewer-body{flex:1;position:relative;overflow:hidden;display:flex;min-height:0}


/* FreeCAD 顶部小工具条 */
.fc-toolbar{position:absolute;top:6px;left:8px;z-index:15;display:flex;align-items:center;gap:6px;background:rgba(22,33,62,.85);border:1px solid #2a2a4e;border-radius:6px;padding:3px 6px}
.fc-btn-sm{background:#4f46e5;color:#fff;border:none;border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer}
.fc-btn-sm:hover{background:#4338ca}
.fc-file-sm{font-size:10px;color:#aaa;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fc-status-sm{font-size:10px;color:#4ade80}
.fc-status-sm.err{color:#f87171}

.viewer-win{flex:1;position:relative;overflow:hidden;display:flex;min-height:0}
.viewer-win.drawer-content{display:block;overflow-y:auto}

.viewer-canvas{flex:1;position:relative;min-width:0}
.viewer-side{background:#16213e;border-left:1px solid #2a2a4e;display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;transition:width .25s ease;min-width:0}
.viewer-side.collapsed{width:0 !important;border-left:none}
.side-toggle{
  position:absolute;top:50%;transform:translateY(-50%);z-index:20;background:#16213e;color:#aaa;
  border:1px solid #2a2a4e;border-radius:6px 0 0 6px;cursor:pointer;font-size:11px;padding:10px 3px;right:0;
}
.side-toggle:hover{color:#fff;background:#4f46e5;border-color:#4f46e5}
.viewer-side h4{padding:10px 12px;margin:0;font-size:12px;color:#888;border-bottom:1px solid #2a2a4e;flex-shrink:0}
.fc-hint{font-size:11px;color:#888;line-height:1.6;margin:0}
.fc-btn{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:8px 10px;font-size:12px;cursor:pointer}
.fc-btn:hover{background:#4338ca}
.fc-file{font-size:11px;color:#e0e0e0;background:rgba(255,255,255,.06);border-radius:5px;padding:6px 8px;word-break:break-all}
.fc-status{font-size:11px;color:#4ade80}

/* 抽屉内容区(files/rules/docs) */
.drawer-content{flex:1;overflow-y:auto;padding:10px 12px;background:#16213e;color:#ccc;font-size:12px}
.drawer-hd{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.drawer-hd h4{margin:0;font-size:13px;color:#e0e0e0}
.drawer-sub{font-size:10px;color:#888}
.drawer-refresh{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:#aaa;border-radius:4px;padding:2px 6px;font-size:10px;cursor:pointer;margin-left:auto}
.drawer-refresh:hover{background:rgba(255,255,255,.12);color:#fff}

/* 工程图纸弹层 */
.drawing-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:300;display:flex;align-items:center;justify-content:center}
.drawing-modal{background:#fff;border-radius:10px;width:min(900px,92vw);height:min(680px,90vh);display:flex;flex-direction:column;box-shadow:0 10px 40px rgba(0,0,0,.3)}
.drawing-hd{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #e5e5e5}
.drawing-hd h3{font-size:15px;margin:0;font-weight:600;color:#333}
.drawing-file{font-size:11px;color:#999;font-family:monospace;margin-left:6px}
.drawing-pdf{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:12px;cursor:pointer;margin-left:auto}
.drawing-close{background:none;border:none;font-size:20px;cursor:pointer;color:#999}
.drawing-close:hover{color:#333}
.drawing-err{color:#dc2626;padding:20px;text-align:center;font-size:13px}
.drawing-loading{color:#999;padding:40px;text-align:center;font-size:13px}
.drawing-body{flex:1;overflow:auto;padding:12px;background:#fafafa}
.drawing-body :deep(svg){width:100%;height:auto;background:#fff;border:1px solid #e5e5e5}

.file-group{margin-bottom:8px}
.file-group-hd{display:flex;align-items:center;gap:6px;padding:5px 8px;background:rgba(255,255,255,.05);border-radius:5px;margin-bottom:3px}
.file-group-time{font-size:11px;color:#8ab4f8;font-family:monospace;flex:1}
.file-group-count{font-size:10px;color:#888}

.drawer-list{display:flex;flex-direction:column;gap:4px}
.drawer-item{display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:5px;cursor:pointer;font-size:12px}
.drawer-item:hover{background:rgba(255,255,255,.08)}
.drawer-type{font-size:9px;color:#4f46e5;background:rgba(79,70,229,.2);padding:1px 5px;border-radius:4px;flex-shrink:0}
.drawer-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#ccc}
.drawer-actions{display:flex;gap:4px}
.drawer-item .mini{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:#aaa;border-radius:4px;padding:1px 6px;font-size:10px;cursor:pointer}
.drawer-item .mini:hover{color:#fff}
.drawer-empty{color:#777;text-align:center;padding:24px 0;font-size:12px;line-height:1.8}
.drawer-textarea{width:100%;min-height:200px;background:#1a1a2e;color:#ccc;border:1px solid #2a2a4e;border-radius:6px;padding:8px;font-size:12px;resize:vertical;outline:none;font-family:inherit;line-height:1.6}
.drawer-textarea:focus{border-color:#4f46e5}
.drawer-doc{display:flex;flex-direction:column;gap:4px}

.part-list{flex:1;overflow-y:auto;padding:4px 0}
.part-item{display:flex;align-items:center;padding:5px 10px;font-size:12px;color:#ccc;cursor:pointer;gap:6px;border-left:3px solid transparent}
.part-item:hover{background:rgba(255,255,255,0.06)}
.part-item.sel{border-left-color:#4f46e5;background:rgba(79,70,229,0.15)}
.part-item .dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.part-item .name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.part-item .hide-btn{opacity:0;background:none;border:none;color:#666;cursor:pointer;font-size:13px;padding:0 4px}
.part-item:hover .hide-btn{opacity:1}
.part-item .hide-btn:hover{color:#fff}
.part-item.hidden .dot{opacity:0.2}
.part-item.hidden .name{opacity:0.3;text-decoration:line-through}
.angle-display{padding:6px 12px;border-top:1px solid #2a2a4e;flex-shrink:0}
.angle-row{display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:11px}
.angle-label{color:#888}
.angle-val{color:#e0e0e0;font-family:monospace;font-size:12px;min-width:42px;text-align:right}
.viewer-info{position:absolute;bottom:80px;left:220px;background:rgba(0,0,0,0.75);color:#e0e0e0;padding:8px 14px;border-radius:6px;font-size:12px;font-family:monospace;display:none;pointer-events:none;z-index:15;max-width:400px;line-height:1.5}
.viewer-tools{display:flex;gap:4px;padding:6px 12px;border-top:1px solid #2a2a4e;flex-wrap:wrap;flex-shrink:0}
.viewer-tools button{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);color:#aaa;padding:3px 8px;border-radius:4px;font-size:10px;cursor:pointer}
.viewer-tools button:hover{background:rgba(255,255,255,0.12);color:#fff}
.viewer-tools button.on{background:#4f46e5;border-color:#4f46e5;color:#fff}
</style>
<style>
.anvil-tooltip{position:fixed;display:none;background:rgba(0,0,0,0.85);color:#fff;padding:4px 10px;border-radius:4px;font-size:12px;pointer-events:none;z-index:9999;white-space:nowrap}
.viewer-loading{position:absolute;inset:0;z-index:50;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(26,26,46,0.92);transition:opacity .35s;pointer-events:none}
.viewer-loading.vloader-done{opacity:0}
.viewer-loading:not(.vloader-done){pointer-events:auto}
.vloader-spin{width:36px;height:36px;border:3px solid rgba(255,255,255,.1);border-top-color:#4f46e5;border-radius:50%;animation:vspin .8s linear infinite;margin-bottom:12px}
@keyframes vspin{to{transform:rotate(360deg)}}
.vloader-text{color:#999;font-size:12px;font-family:monospace}
</style>
