<template>
  <div class="demo-view" :class="{ dvm: isMobile }">
    <div class="demo-hd">
      <div>
        <div class="demo-title">{{ demo?.title || '演示' }}</div>
        <div class="demo-sub">{{ demo?.subtitle }}</div>
      </div>
      <div class="demo-ctrl">
        <button class="dbtn" @click="togglePlay">{{ playing ? '⏸ 暂停' : '▶ 播放' }}</button>
        <button class="dbtn" @click="prevStep" :disabled="step === 0">⏮ 上一步</button>
        <button class="dbtn" @click="nextStep" :disabled="step >= total - 1">下一步 ⏭</button>
        <button class="dbtn" @click="restart">↻ 重播</button>
        <label class="dchk"><input type="checkbox" v-model="voiceOn" /> 配音</label>
      </div>
    </div>

    <div class="demo-body">
      <!-- 左:指令输入(打字机) + 字幕 -->
      <div class="demo-left">
        <div class="script-list">
          <div class="sl-title">演示脚本</div>
          <div v-for="(t, k) in demoList" :key="k" class="sl-item"
               :class="{ on: k === demoName }" @click="switchDemo(k)">{{ t }}</div>
          <div class="sl-title" style="margin-top:12px">从项目生成</div>
          <div class="gen-row">
            <select v-model="genProject" class="gen-sel">
              <option value="" disabled>选择设计项目…</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <button class="gen-btn" :disabled="!genProject || generating" @click="generate">
              {{ generating ? '生成中…' : '✨ 生成' }}
            </button>
          </div>
          <div v-if="genMsg" class="gen-msg" :class="{ err: genErr }">{{ genMsg }}</div>
        </div>
        <div class="chat-frame">
          <div class="cf-title">💬 设计指令</div>
          <template v-if="demo">
            <div class="cf-msg user"><span class="cf-role">用户</span>{{ typedCmd }}<span v-if="typing" class="caret">▌</span></div>
            <div v-if="!typing" class="cf-msg ai">
              <span class="cf-role">Anvil</span>{{ aiReply }}
              <div class="cf-files">📦 {{ cur.caption }} · 已生成 STEP/STL</div>
            </div>
          </template>
          <div v-else class="cf-empty">尚未选择演示。从上方演示脚本中选择，或从设计项目生成一份。</div>
        </div>
        <div v-if="demo" class="narration" :class="{ on: narrHighlight }">{{ cur.narration }}</div>
        <div v-if="demo" class="facts">
          <div v-for="f in cur.facts" :key="f" class="fact">✓ {{ f }}</div>
        </div>
        <div v-if="demo" class="step-dots">
          <div v-for="(s, i) in demo?.steps || []" :key="i"
               class="dot" :class="{ done: Number(i) < step, cur: Number(i) === step }"
               @click="jumpTo(Number(i))">{{ Number(i) + 1 }}</div>
        </div>
      </div>

      <!-- 右:3D 阶段呈现 -->
      <!-- 右栏由 three/原生 DOM 全权管理(Vue 不渲染此子树:
           曾因 Vue patch 与 innerHTML 清写边界交错致 caption 永不更新) -->
      <div class="demo-right">
        <div v-if="!demo" class="v3d-empty">未选择演示<br /><span>从左侧选择演示脚本，或从设计项目生成</span></div>
        <div id="demo-right-host"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const demo = ref<any>(null)
const winW = ref(window.innerWidth)
const isMobile = computed(() => winW.value < 992)
window.addEventListener('resize', () => { winW.value = window.innerWidth })
const demoName = ref(localStorage.getItem('anvil_demo_name') || '')
const demoList = ref<Record<string, string>>({})
const projects = ref<any[]>([])
const genProject = ref('')
const generating = ref(false)
const genMsg = ref('')
const genErr = ref(false)

async function loadProjects() {
  try {
    const r = await fetch('/api/projects', { headers: authHeaders() })
    const d = await r.json()
    projects.value = (Array.isArray(d) ? d : d.projects || []).slice(0, 30)
  } catch { /* ignore */ }
}

async function generate() {
  if (!genProject.value) return
  generating.value = true; genMsg.value = ''; genErr.value = false
  try {
    const proj = projects.value.find((p: any) => p.id === genProject.value)
    const r = await fetch('/api/demo/generate', {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_ref: genProject.value, demo_name: proj ? 'demo_' + proj.name : '' })
    })
    const d = await r.json()
    if (!r.ok || !d.ok) throw new Error(d.detail || d.message || '生成失败')
    genMsg.value = '已生成 ' + d.steps + ' 步演示'
    await loadDemoList()
    await switchDemo(d.demo)
  } catch (e: any) {
    genErr.value = true; genMsg.value = e.message || '生成失败'
  } finally { generating.value = false }
}
async function loadDemoList() {
  try {
    const r = await fetch('/api/demo', { headers: authHeaders() })
    const d = await r.json()
    demoList.value = d.demos || {}
    // 无默认演示(2026-09-06 用户定):未选(或所选已不存在)则空态,
    // 不自动 fallback 到清单第一项——没选就不演示
    if (demoName.value && !demoList.value[demoName.value]) {
      demoName.value = ''
      localStorage.removeItem('anvil_demo_name')
    }
  } catch { /* ignore */ }
}
const step = ref(0)
const playing = ref(false)
const voiceOn = ref(true)
const typing = ref(false)
const typedCmd = ref('')
const narrHighlight = ref(false)
const loading3d = ref(false)
const v3dEl = ref<HTMLElement>()
const total = computed(() => demo.value?.steps?.length || 0)
const cur = computed<any>(() => (demo.value?.steps || [])[step.value] || { cmd: '', narration: '', caption: '', facts: [] })
const capNow = computed(() => {
  const s = (demo.value?.steps || [])[step.value]
  return (s && s.caption) || ''
})
const aiReply = computed(() => '已完成建模。' + (cur.value.caption || ''))

let audio: HTMLAudioElement | null = null
let typeTimer: any = null
let rotTimer: any = null
let threeRef: any = null

const authHeaders = () => {
  const t = localStorage.getItem('anvil_token')
  return t ? { Authorization: 'Bearer ' + t } : {}
}

async function switchDemo(k: string) {
  // 早退仅当同名且已加载成功——demo 为空(加载失败/空态)时同名也必须重试加载,
  // 否则点击列表项永远无响应
  if (k === demoName.value && demo.value) return
  demoName.value = k
  await loadDemo()
}

async function loadDemo() {
  const r = await fetch('/api/demo/' + demoName.value, { headers: authHeaders() })
  if (!r.ok) {
    // 演示不存在(如项目被清)→空态并清记忆,否则同名演示将因早退条件永远点不开
    demo.value = null
    demoName.value = ''
    localStorage.removeItem('anvil_demo_name')
    return
  }
  demo.value = await r.json()
  localStorage.setItem('anvil_demo_name', demoName.value)
  enterStep(0)
}

// ---- 打字机 ----
function startTyping() {
  typing.value = true
  typedCmd.value = ''
  const text = cur.value.cmd || ''
  let i = 0
  clearInterval(typeTimer)
  typeTimer = setInterval(() => {
    typedCmd.value = text.slice(0, ++i)
    if (i >= text.length) { clearInterval(typeTimer); typing.value = false }
  }, 38)
}

// ---- 3D 呈现(STL 加载 + 生长动画:从透明到实体 + 自动旋转) ----
// 视口单例(演示页内复用 renderer/scene/camera,只换 mesh——防每步新建
// WebGL context 累积导致的抖动/内存上涨;卸载时统一释放)
let vp: any = {}
async function ensureViewport(el: HTMLElement) {
  if (vp.renderer && vp.el === el) return vp
  if (rotTimer) cancelAnimationFrame(rotTimer)
  // 释放旧实例
  try { vp.controls?.dispose?.() } catch { /* ignore */ }
  try { vp.renderer?.dispose?.(); vp.renderer?.forceContextLoss?.() } catch { /* ignore */ }
  el.innerHTML = ''
  const THREE = await import('three')
  const { OrbitControls } = await import('three/addons/controls/OrbitControls.js')
  const rect = el.getBoundingClientRect()
  const w = Math.round(rect.width) || 640, h = Math.round(rect.height) || 480
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x14162a)
  const camera = new THREE.PerspectiveCamera(32, w / h, 1, 5000)
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setSize(w, h, false)  // updateStyle=false:防 resize 反馈循环(抖动)
  // DPR 上取整(1.5→2):分数缩放因子在高分屏上产生亚像素重采样,
  // 自转时模型边缘持续颤动(瞻动);整倍 DPR 消除该源
  renderer.setPixelRatio(Math.ceil(Math.min(window.devicePixelRatio, 2)))
  renderer.domElement.style.width = '100%'
  renderer.domElement.style.height = '100%'
  renderer.domElement.style.imageRendering = 'auto'
  el.appendChild(renderer.domElement)
  // 纯放映模式:禁用一切指针/滚轮交互(演示页相机由 autoRotate 独占,
  // 消除用户操作与环绕争抢同一相机的整族问题)
  // 放映相机:关 damping(无交互不需要阻尼;开着时帧间隔波动会转化为
  // 角速度波动 = 自转"打滑"感),改固定角速度显式旋转(每帧 0.35°,60fps≈21°/s)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  controls.autoRotate = false
  controls.enableRotate = false
  controls.enablePan = false
  controls.enableZoom = false
  renderer.domElement.style.pointerEvents = 'none'
  scene.add(new THREE.HemisphereLight(0x8899ff, 0x222244, 1.4))
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(300, 400, 200); scene.add(key)
  // resize 跟随(非零防御)
  const ro = new ResizeObserver(() => {
    const r = el.getBoundingClientRect()
    if (r.width > 20 && r.height > 20) {
      renderer.setSize(Math.round(r.width), Math.round(r.height), false)
      camera.aspect = r.width / r.height
      camera.updateProjectionMatrix()
    }
  })
  ro.observe(el)
  vp = { THREE, scene, camera, renderer, controls, ro, el }
  return vp
}

async function showStep(i: number) {
  const cap0 = document.getElementById('demo-v3d-cap')
  if (cap0) cap0.textContent = '加载第 ' + (i + 1) + ' 步模型…'
  loading3d.value = true
  await new Promise(r => setTimeout(r, 0))  // 绕开 nextTick 调度(疑似挂起,定位用)
  // 杀上一步渲染循环:ensureViewport 复用分支不重建,旧 tick 若不清
  // 每步叠一个循环(多循环 controls.update 交错 = 播放中抖动根因)
  if (rotTimer) { cancelAnimationFrame(rotTimer); rotTimer = 0 }
  // 右栏骨架:原生 DOM 构建(Vue 不参与),caption/canvas/hint 同源更新
  const getHost = () => document.getElementById('demo-v3d-host') as HTMLElement | null
  let el2 = getHost()
  if (!el2) {
    const right = document.getElementById('demo-right-host')
    if (!right) return
    right.innerHTML =
      '<div class="v3d" id="demo-v3d-host"></div>' +
      '<div class="v3d-cap" id="demo-v3d-cap"></div>' +
      '<div class="v3d-hint">自动环绕展示</div>'
    el2 = getHost()
  }
  if (!el2) return
  const { THREE, scene, camera, renderer, controls } = await ensureViewport(el2)
  const { STLLoader } = await import('three/addons/loaders/STLLoader.js')
  threeRef = THREE
  // 清上一部的模型(保留场景/灯/网格基础件)
  for (const o of [...scene.children]) {
    if (o.userData?.demoMesh || o.type === 'GridHelper') scene.remove(o)
  }
  vp.mesh = null

  const s = demo.value.steps[i]
  // 3D 加载全程显式失败:STL 缺失/HTTP 错/解析错都上屏,杜绝"语音文字有、3D 静默无"
  try {
    if (!s?.stl_file) throw new Error('本步无 STL 产物（演示数据缺失）')
    const url = `/api/project/${demo.value.project_ref}/cad/${s.stl_file}`
    const resp = await fetch(url, { headers: authHeaders() })
    if (!resp.ok) throw new Error('STL HTTP ' + resp.status)
    const buf = await resp.arrayBuffer()
    const geom = new STLLoader().parse(buf)
    geom.computeVertexNormals()
    geom.rotateX(-Math.PI / 2)
    geom.computeBoundingBox()
    const bb = geom.boundingBox!
    const size = Math.max(bb.max.x - bb.min.x, bb.max.y - bb.min.y, bb.max.z - bb.min.z) || 1
    const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
      color: 0x5b8cff, metalness: 0.35, roughness: 0.45, transparent: true, opacity: 0 }))
    mesh.userData.demoMesh = true
    const cx = (bb.max.x + bb.min.x) / 2, cy = (bb.max.y + bb.min.y) / 2, cz = (bb.max.z + bb.min.z) / 2
    mesh.position.set(-cx, -cy, -cz)
    scene.add(mesh)
    const grid = new THREE.GridHelper(size * 3, 24, 0x3a3f66, 0x282c4a)
    scene.add(grid)
    camera.near = Math.max(0.1, size * 0.002); camera.far = size * 50
    camera.updateProjectionMatrix()
    camera.position.set(size * 0.9, size * 0.8, size * 1.5)
    controls.target.set(0, 0, 0)

    // 相机平滑补间:从当前位置飞到新取景点(700ms easeInOut),
    // 消除切步硬 set 造成的视角跃变
    const from = camera.position.clone()
    const to = new THREE.Vector3(size * 0.9, size * 0.8, size * 1.5)

    const t0 = performance.now()
    let tweenDone = false
    let azimuth = Math.atan2(camera.position.x, camera.position.z)  // 当前方位角
    const radius = camera.position.length()
    const elev = camera.position.y / radius
    const tick = () => {
      rotTimer = requestAnimationFrame(tick)
      const k = Math.min(1, (performance.now() - t0) / 900)
      ;(mesh.material as any).opacity = k
      if (!tweenDone) {
        // 补间期:相机受控飞向新取景点(与自旋分离,互不干扰)
        const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2
        camera.position.lerpVectors(from, to, e)
        if (k >= 1) {
          tweenDone = true
          azimuth = Math.atan2(camera.position.x, camera.position.z)
        }
      } else {
        // 常驻期:固定角速度绕 target 匀速环绕(不依赖帧时长,杜绝打滑)
        azimuth += 0.006  // ≈0.34°/帧
        const r2 = Math.sqrt(Math.max(0.0001, 1 - elev * elev)) * radius
        camera.position.set(Math.sin(azimuth) * r2, elev * radius, Math.cos(azimuth) * r2)
        camera.lookAt(0, 0, 0)
      }
      renderer.render(scene, camera)
    }
    tick()
    const capEl = document.getElementById('demo-v3d-cap')
    if (capEl) capEl.textContent = (demo.value?.steps?.[i]?.caption) || ''
  } catch (e: any) {
    const capEl = document.getElementById('demo-v3d-cap')
    if (capEl) capEl.textContent = '⚠ 3D 加载失败: ' + (e?.message || e)
  }
  loading3d.value = false
}

// ---- 配音 ----
function playAudio(i: number) {
  stopAudio()
  if (!voiceOn.value) return
  // 单例 Audio(自动播放策略按元素解锁:首次手势播放后,复用元素永久可播;
  // 每次 new Audio() 会被重新拦截 → 切步静音的根因)
  if (!audio) audio = new Audio()
  audio.onended = null
  audio.pause()
  audio.src = `/api/demo/${demoName.value}/audio/${i}`
  audio.load()               // 强制重载:复用元素换 src 后部分移动端不重置位置,
  audio.currentTime = 0      // 从旧位置续播=开头字被吃的根因
  audio.play().catch(() => { /* 首次被拒:点播放按钮即解锁 */ })
  narrHighlight.value = true
}
function stopAudio() {
  if (audio) { audio.pause() }  // 不销毁:保住已解锁的元素(销毁后 new 会被 autoplay 重新拦截)
  narrHighlight.value = false
}

// ---- 步进控制 ----
let stepTimer: any = null
function stepDuration(i: number): number {
  // 步时长:打字时间 + 解说时长(按字数 4字/秒 估) + 停顿,音频结束可提前
  const cmdT = ((demo.value?.steps[i]?.cmd || '').length * 38) / 1000 + 400
  // 兜底时钟(仅在音频不可播时生效):
  // 开配音 → 保守长时限(估长 1.6 倍+8s 余量,宁慢勿切——音频 onended 才是正常推进器)
  // 关配音 → 6s 阅读节奏
  if (voiceOn.value) {
    return cmdT + ((demo.value?.steps[i]?.narration || '').length / 4.6) * 1600 + 8000
  }
  return cmdT + 6000
}
async function enterStep(i: number) {
  step.value = i
  startTyping()
  showStep(i)  // 异步加载,不阻塞节奏
  playAudio(i)
  // 时间轴驱动(主时钟):配音事件只做提前,不做唯一触发(自动播放被拒也不卡死)
  clearTimeout(stepTimer)
  stepTimer = setTimeout(() => {
    if (playing.value && step.value === i && step.value < total.value - 1) nextStep()
    else if (playing.value && step.value === total.value - 1) playing.value = false
  }, stepDuration(i))
}
function nextStep() { if (step.value < total.value - 1) enterStep(step.value + 1) }
function prevStep() { if (step.value > 0) enterStep(step.value - 1) }
function jumpTo(i: number) { playing.value = false; enterStep(i) }
function restart() { enterStep(0); playing.value = true }
function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    if (typing.value) return  // 当前步播完打字/音频会自动推进
    if (audio?.paused) audio?.play()
    scheduleNext()
  } else {
    audio?.pause()
  }
}
function scheduleNext() {
  // 音频播完提前推进;主时钟(enterStep 的 setTimeout)兜底,
  // 浏览器拒播音频/静音环境都不会卡步。
  if (audio && voiceOn.value) {
    audio.onended = () => {
      if (playing.value && step.value < total.value - 1) {
        clearTimeout(stepTimer)
        nextStep()
      } else if (playing.value) playing.value = false
    }
  }
}
watch(typing, (v) => { if (!v && playing.value) scheduleNext() })

// 暴露给宿主/调试:window.__demo = {enterStep,jumpTo} (生产可用作自动化驱动)
;(window as any).__demo = { enterStep, jumpTo, nextStep, prevStep, restart }
defineExpose({ enterStep, jumpTo })

onMounted(async () => {
  await Promise.all([loadDemoList(), loadProjects()])
  if (demoName.value) await loadDemo()  // 没选演示就不演示(空态引导选择/生成)
})
onBeforeUnmount(() => {
  stopAudio(); clearInterval(typeTimer); clearTimeout(stepTimer)
  if (rotTimer) cancelAnimationFrame(rotTimer)
  // 释放 WebGL 上下文 + 清右栏原生 DOM
  const right = document.getElementById('demo-right-host')
  if (right) right.innerHTML = ''
  vp = {}
})
</script>

<style scoped>
.demo-view{height:100%;display:flex;flex-direction:column;background:#101223;color:#e8eaf6}
.demo-hd{display:flex;justify-content:space-between;align-items:center;padding:14px 22px;border-bottom:1px solid #232645}
.demo-title{font-size:19px;font-weight:700}
.demo-sub{font-size:12px;color:#8a90b8;margin-top:2px}
.script-list{background:#171a30;border:1px solid #2a2e52;border-radius:10px;padding:10px}
.sl-title{font-size:12px;color:#7d84b5;margin-bottom:8px}
.sl-item{padding:7px 10px;border-radius:7px;font-size:13px;color:#aab1dd;cursor:pointer;margin-bottom:4px;border:1px solid transparent}
.sl-item:hover{background:#202448}
.sl-item.on{background:#2a4fd7;color:#fff;border-color:#5b8cff}
.gen-row{display:flex;gap:6px}
.gen-sel{flex:1;background:#14162c;border:1px solid #3a4070;color:#cfd4ff;border-radius:6px;padding:5px 6px;font-size:12px;min-width:0}
.gen-btn{background:#1d5f3a;border:1px solid #2c8b57;color:#8fe6b0;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}
.gen-btn:disabled{opacity:.5;cursor:default}
.gen-msg{font-size:12px;color:#7ee2a0;margin-top:6px}
.gen-msg.err{color:#ff8a8a}
.dsel{background:#1b1e3a;border:1px solid #3a4070;color:#cfd4ff;border-radius:6px;padding:5px 8px;font-size:13px;max-width:220px}
.demo-ctrl{display:flex;gap:8px;align-items:center}
/* 移动端(类驱动):操作按钮组横向滑动 */
.demo-view.dvm .demo-ctrl{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;max-width:100%;padding-bottom:2px}
.demo-view.dvm .demo-ctrl::-webkit-scrollbar{display:none}
.demo-view.dvm .demo-ctrl .dbtn{flex-shrink:0}
.dbtn{background:#2a2f55;border:1px solid #3a4070;color:#cfd4ff;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:13px}
.dbtn:hover:not(:disabled){background:#343b6e}
.dbtn:disabled{opacity:.4;cursor:default}
.dchk{font-size:13px;color:#9aa0cc;display:flex;gap:4px;align-items:center;margin-left:6px}
.demo-body{flex:1;display:flex;min-height:0}
/* 移动端(类驱动,.dvm 由 JS isMobile 挂,避 scoped+media 真机坑):
   3D 区在上,指令/字幕在下 */
.demo-view.dvm .demo-body{flex-direction:column;overflow-y:auto}
.demo-view.dvm .demo-right{order:-1}
.demo-view.dvm .demo-right{min-height:52vh;flex:none}
.demo-view.dvm .demo-left{width:100%;min-width:0;flex:none;border-right:none;padding:12px}
.demo-view.dvm #demo-right-host{min-height:44vh}
.demo-left{width:44%;min-width:380px;display:flex;flex-direction:column;padding:18px;gap:14px;border-right:1px solid #232645}
.chat-frame{background:#171a30;border:1px solid #2a2e52;border-radius:10px;padding:14px}
.cf-title{font-size:12px;color:#7d84b5;margin-bottom:10px}
.cf-msg{border-radius:10px;padding:10px 12px;margin:6px 0;font-size:14px;line-height:1.6}
.cf-msg.user{background:#24408f;color:#fff}
.cf-msg.ai{background:#1d2140;color:#c8cdf5}
.cf-role{font-size:11px;color:#9fb0e8;margin-right:8px}
.cf-files{font-size:12px;color:#7ee2a0;margin-top:6px}
.caret{animation:blink 0.8s infinite}
@keyframes blink{50%{opacity:0}}
.narration{background:#181c38;border-left:3px solid #5b8cff;border-radius:6px;padding:12px 14px;font-size:14px;line-height:1.8;color:#c9cdf0;min-height:96px;transition:box-shadow .3s}
.narration.on{box-shadow:0 0 0 1px #5b8cff55}
.facts{display:flex;flex-direction:column;gap:6px}
.fact{font-size:13px;color:#8fe0a8;background:#13251d44;border:1px solid #1e3a2c;border-radius:6px;padding:6px 10px}
.step-dots{margin-top:auto;display:flex;gap:10px;padding-top:10px}
.dot{width:30px;height:30px;border-radius:50%;background:#232750;color:#888fc4;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:13px;border:1px solid #32366a}
.dot.done{background:#1d4d33;color:#7ee2a0;border-color:#2c6b47}
.dot.cur{background:#2a4fd7;color:#fff;border-color:#5b8cff;transform:scale(1.12)}
.demo-right{flex:1;display:flex;flex-direction:column;min-width:0;position:relative}
.v3d-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#8a90b8;font-size:17px;text-align:center;line-height:2}
.v3d-empty span{font-size:13px;color:#666d99}
.cf-empty{padding:24px 12px;color:#8a90b8;font-size:14px;text-align:center}
.v3d{flex:1;position:relative;min-height:0}
.v3d canvas{display:block}
.v3d-loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#8a90b8;background:#14162acc;z-index:2}
.v3d-cap{text-align:center;font-size:15px;font-weight:600;padding:10px}
.v3d-hint{text-align:center;font-size:11px;color:#666d99;padding-bottom:8px}
</style>

<style>
/* 右栏为原生 DOM(Vue 不渲染),样式须全局 */
.demo-right{flex:1;display:flex;flex-direction:column;min-width:0}
#demo-right-host{flex:1;display:flex;flex-direction:column;min-height:0}
#demo-right-host .v3d{flex:1;position:relative;min-height:0;overflow:hidden;max-width:100%}
#demo-right-host .v3d canvas{display:block}
#demo-right-host .v3d-cap{text-align:center;font-size:15px;font-weight:600;padding:10px;color:#e8eaf6}
#demo-right-host .v3d-hint{text-align:center;font-size:11px;color:#666d99;padding-bottom:8px}
</style>
