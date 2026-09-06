<script setup lang="ts">
import { ref } from 'vue'
import { getUser } from '@/api'

defineOptions({ name: 'UserGuide' })

const user = ref(getUser())
const roleName = (r?: string | null) =>
  ({ admin: '管理员', engineer: '工程师', viewer: '访客' } as Record<string, string>)[r || ''] || r || '—'

const sections = ref([
  { key: 'start', label: '🚀 快速开始', open: true },
  { key: 'tools', label: '🧰 工具箱', open: false },
  { key: 'model', label: '🤖 模型配置', open: false },
  { key: 'share', label: '🔗 数据共享', open: false },
  { key: 'perm', label: '🔐 权限申请', open: false },
  { key: 'admin', label: '🛡️ 管理功能', open: false },
])
function toggle(key: string) {
  const s = sections.value.find(x => x.key === key)
  if (s) s.open = !s.open
}
</script>

<template>
  <div class="guide-view">
    <div class="guide-hd">
      <h3>📖 用户指南</h3>
      <span class="guide-sub">Anvil AI 机械设计工具 · 使用说明</span>
    </div>

    <div class="guide-body">
      <div class="guide-card">
        <h4>👤 当前账号</h4>
        <p>用户名: <b>{{ user?.username }}</b> · 角色: <b>{{ roleName(user?.role) }}</b></p>
        <p class="guide-tip">角色决定你的默认权限:管理员(全部)/ 工程师(设计+工具)/ 访客(只读+基础工具)。未授权工具可在工具箱中点「申请」。</p>
      </div>

      <div v-for="s in sections" :key="s.key" class="guide-card">
        <div class="guide-section-hd" @click="toggle(s.key)">
          <span>{{ s.label }}</span>
          <span class="guide-arrow">{{ s.open ? '▾' : '▸' }}</span>
        </div>
        <div v-if="s.open" class="guide-content">
          <template v-if="s.key === 'start'">
            <ol>
              <li><b>登录/注册</b>:登录页可切换注册(默认「访客」权限,由管理员提升)。</li>
              <li><b>新建项目</b>:左侧「设计」视图 →「+ New Project」,每个用户有独立目录。</li>
              <li><b>开始设计</b>:在对话输入框描述需求(如"用 shell_box 做个盒子 100x80x60 壁厚5"),AI 会解析需求、建模并生成 STEP/STL。</li>
              <li><b>查看结果</b>:消息下方的文件链接可「3D」预览(右侧抽屉可展开/收起/调宽)、「⬇」下载。</li>
              <li><b>多组件装配</b>:描述多个零件,自动生成装配图;每轮结果独立目录保存,历史可追溯。</li>
            </ol>
          </template>

          <template v-else-if="s.key === 'tools'">
            <p>工具箱中的工具按你的权限显示;未授权的工具显示「申请」按钮。</p>
            <table class="guide-table">
              <thead><tr><th>工具</th><th>用途</th><th>默认权限</th></tr></thead>
              <tbody>
                <tr><td>✏️ 手绘草图</td><td>绘图板手绘+语音,AI 识别建模</td><td>工程师/访客</td></tr>
                <tr><td>🧩 图元库</td><td>点选图元填参数,快速生成零件</td><td>工程师</td></tr>
                <tr><td>📊 项目甘特图</td><td>任务计划与里程碑,树形结构</td><td>工程师/访客</td></tr>
                <tr><td>🔩 标准件查询</td><td>标准件/非标件/行业/企业件库查询</td><td>工程师</td></tr>
                <tr><td>🔍 OCR 识别</td><td>图片/图纸文字识别(本地免费)</td><td>全部</td></tr>
                <tr><td>🎤 语音输入</td><td>语音转文字(浏览器/whisper 免费)</td><td>全部</td></tr>
              </tbody>
            </table>
          </template>

          <template v-else-if="s.key === 'model'">
            <p>在「设置 → 模型配置」中可自设三类模型(留空则用系统默认):</p>
            <ul>
              <li><b>推理模型</b>:设计对话/Agent 使用(如 DeepSeek)。</li>
              <li><b>视觉模型</b>:手绘识别/图像理解(如 Moonshot Vision)。</li>
              <li><b>语音模型</b>:语音转写(未配置时自动用免费 whisper)。</li>
            </ul>
            <p class="guide-tip">配置保存在你自己的账号下,仅你自己生效;API Key 加密存放,不随代码分发。</p>
          </template>

          <template v-else-if="s.key === 'share'">
            <p>项目列表中的 🔗 按钮可把项目共享给其他用户,三级权限:</p>
            <ul>
              <li><b>可读</b>:查看设计结果/日志/文件。</li>
              <li><b>可批注</b>:读 + 写规则/甘特/评审(批注)。</li>
              <li><b>可参与修改</b>:读 + 写 + AI 生成/建模。</li>
            </ul>
            <p class="guide-tip">共享项目会出现在对方的项目列表中(带权限标记);只有项目所有者可删除和共享。</p>
          </template>

          <template v-else-if="s.key === 'perm'">
            <p>工具箱中未授权的工具点「申请」→ 填写理由 → 管理员在「管理 → 权限申请」中审批。</p>
            <ul>
              <li>审批通过后自动完成授权,刷新即可使用。</li>
              <li>管理员也可在「管理 → 工具授权」中直接授予/回收(角色级或用户级)。</li>
            </ul>
          </template>

          <template v-else-if="s.key === 'admin'">
            <p>管理员专属「管理」入口包含:</p>
            <ul>
              <li><b>用户管理</b>:增删改查/角色分级/启停/重置密码。</li>
              <li><b>权限申请</b>:审批用户工具申请。</li>
              <li><b>工具授权</b>:角色×工具、用户×工具授权矩阵。</li>
              <li><b>Token 消耗</b>:按用户/模型类型统计 token 用量。</li>
              <li><b>登录日志</b>:登录成功/失败记录(IP/UA)。</li>
              <li><b>系统日志</b>:下载追溯 + 各用户设计日志。</li>
            </ul>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.guide-view{flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;padding:16px 20px;overflow-y:auto}
.guide-hd{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.guide-hd h3{font-size:16px;font-weight:700;color:#333;margin:0}
.guide-sub{font-size:11px;color:#999}
.guide-body{max-width:760px}
.guide-card{background:#fafafa;border:1px solid #e5e5e5;border-radius:10px;padding:14px 18px;margin-bottom:12px}
.guide-card h4{margin:0 0 8px;font-size:14px;color:#333}
.guide-card p{margin:4px 0;font-size:13px;color:#444;line-height:1.7}
.guide-card ol,.guide-card ul{margin:6px 0;padding-left:22px}
.guide-card li{font-size:13px;color:#444;line-height:1.8}
.guide-tip{font-size:12px;color:#888;background:#f0f2f5;border-radius:6px;padding:6px 10px}
.guide-section-hd{display:flex;align-items:center;justify-content:space-between;cursor:pointer;font-size:14px;font-weight:600;color:#333}
.guide-arrow{color:#999;font-size:12px}
.guide-content{margin-top:10px;border-top:1px solid #eee;padding-top:10px}
.guide-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
.guide-table th{background:#f0f2f5;font-size:11px;color:#666;text-align:left;padding:6px 10px;border-bottom:1px solid #e5e5e5}
.guide-table td{padding:6px 10px;border-bottom:1px solid #f0f0f0;color:#444}
</style>
