<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import * as api from '@/api'
import AppSidebar from '@/components/AppSidebar.vue'
import DesignView from '@/views/DesignView.vue'
import ToolsView from '@/views/ToolsView.vue'
import SettingsView from '@/views/SettingsView.vue'
import UserGuide from '@/views/UserGuide.vue'
import AdminView from '@/views/AdminView.vue'
import DemoView from '@/views/DemoView.vue'
import NewProjectModal from '@/components/NewProjectModal.vue'
import LoginPage from '@/components/LoginPage.vue'

const store = useAppStore()
const authed = ref(false)
const checking = ref(true)
const currentView = ref('tools')
const winW = ref(window.innerWidth)
const isMobile = computed(() => winW.value < 992)
const sidebarOpen = ref(localStorage.getItem('anvil_sidebar') !== 'closed')
function onResize() { winW.value = window.innerWidth }
window.addEventListener('resize', onResize)
function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
  localStorage.setItem('anvil_sidebar', sidebarOpen.value ? 'open' : 'closed')
}
function closeSidebar() { if (isMobile.value) sidebarOpen.value = false }
// 功能选择持久化：localStorage 记住，刷新恢复
const TOOL_KEY = 'anvil_current_tool'
const currentTool = ref(localStorage.getItem(TOOL_KEY) || 'sketch')
// 记住当前视图（设计/工具箱），刷新恢复
const VIEW_KEY = 'anvil_current_view'
currentView.value = localStorage.getItem(VIEW_KEY) || 'tools'

function selectTool(tool: string) {
  currentTool.value = tool
  localStorage.setItem(TOOL_KEY, tool)
  currentView.value = 'tools'
  localStorage.setItem(VIEW_KEY, 'tools')
}

const BUILD = '927b'
let tapT = 0, tapN = 0
function tapReload() {
  const now = Date.now()
  if (now - tapT > 3000) tapN = 0
  tapT = now; tapN++
  if (tapN >= 3) location.reload()
}
function onDemoProject(pid: string) {
  store.demoTarget = pid
  navigateView('demo')
}
function navigateView(view: string) {
  currentView.value = view
  localStorage.setItem(VIEW_KEY, view)
}

onMounted(async () => {
  const ok = await api.checkAuth()
  authed.value = ok
  checking.value = false
  if (ok) {
    await store.loadProjects().catch(e => console.error('loadProjects failed', e))
    if (!localStorage.getItem(VIEW_KEY)) {
      currentView.value = 'tools'
    }
  }
})
</script>

<template>
  <template v-if="checking">
    <div class="loading-screen">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>
  </template>
  <LoginPage v-else-if="!authed" />
  <template v-else>
    <div v-if="isMobile && sidebarOpen" class="drawer-mask" @click="sidebarOpen = false"></div>
    <button v-if="isMobile && !sidebarOpen" class="m-burger" @click="sidebarOpen = true">☰</button>
    <AppSidebar :active="currentView" :tool="currentTool" :collapsed="!sidebarOpen" :mobile="isMobile"
      @navigate="(v: string) => { navigateView(v); closeSidebar() }"
      @select-tool="(t: string) => { selectTool(t); closeSidebar() }"
      @demo-project="(pid: string) => { onDemoProject(pid); closeSidebar() }"
      @toggle="toggleSidebar" />
    <KeepAlive include="DesignView,ToolsView">
      <DesignView v-if="currentView === 'design'" @goto-sketch="selectTool('sketch')" />
      <ToolsView v-else-if="currentView === 'tools'" :tool="currentTool" :project="store.current" @navigate="navigateView" />
      <SettingsView v-else-if="currentView === 'settings'" />
      <UserGuide v-else-if="currentView === 'guide'" />
      <AdminView v-else-if="currentView === 'admin'" />
    </KeepAlive>
    <!-- DemoView 独立于 KeepAlive:有视口/audio 等全局资源,缓存反致状态错乱 -->
    <DemoView v-if="currentView === 'demo'" />
    <NewProjectModal v-if="store.showModal" />
  </template>
</template>

<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body,#app{height:100%;overflow:hidden}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;background:#fff;color:#1a1a1a}
#app{display:flex}

.loading-screen {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #888;
}
.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.drawer-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000}
 .ver-badge{position:fixed;right:10px;bottom:10px;z-index:998;background:#1b1e3abb;color:#8a90b8;border-radius:10px;font-size:10px;padding:3px 8px;cursor:pointer;user-select:none}
.m-burger{position:fixed;left:10px;top:10px;z-index:999;background:#1b1e3acc;border:1px solid #3a4070;color:#cfd4ff;border-radius:8px;width:40px;height:40px;font-size:18px;cursor:pointer}
@media (max-width:991px){ .main{margin-left:0} }
</style>
