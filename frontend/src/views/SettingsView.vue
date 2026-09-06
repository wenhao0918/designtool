<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getUser, logout, changePassword, getModelConfig, putModelConfig, type ModelConfigs } from '@/api'

const user = ref<{ username: string; role: string; display_name?: string } | null>(null)
const oldPwd = ref('')
const newPwd = ref('')
const pwdMsg = ref('')
const pwdErr = ref('')

// 模型配置
const cfgTab = ref<'inference' | 'vision' | 'voice'>('inference')
const modelCfg = ref<ModelConfigs>({
  inference: { base_url: '', api_key: '', model: '' },
  vision: { base_url: '', api_key: '', model: '' },
  voice: { base_url: '', api_key: '', model: '' },
})
const cfgMsg = ref('')
const cfgErr = ref('')
const cfgLoading = ref(false)

const KIND_LABEL: Record<string, string> = {
  inference: '推理模型(设计对话/Agent)',
  vision: '视觉模型(手绘识别/图像理解)',
  voice: '语音模型(语音转写/识别)',
}

onMounted(async () => {
  user.value = await getUser()
  await loadModelConfig()
})

function doLogout() {
  logout()
  window.location.reload()
}

async function doChangePwd() {
  pwdMsg.value = ''
  pwdErr.value = ''
  if (!oldPwd.value || !newPwd.value) { pwdErr.value = '请填写原密码和新密码'; return }
  try {
    await changePassword(oldPwd.value, newPwd.value)
    pwdMsg.value = '✅ 密码修改成功'
    oldPwd.value = ''
    newPwd.value = ''
  } catch (e: any) {
    pwdErr.value = e?.message || '修改失败'
  }
}

async function loadModelConfig() {
  cfgLoading.value = true
  try {
    const c = await getModelConfig()
    if (c) modelCfg.value = c
  } catch (e: any) {
    cfgErr.value = e?.message || '加载模型配置失败'
  } finally {
    cfgLoading.value = false
  }
}

async function saveModelConfig() {
  cfgMsg.value = ''
  cfgErr.value = ''
  try {
    await putModelConfig(modelCfg.value)
    cfgMsg.value = '✅ 模型配置已保存(各工具统一生效)'
  } catch (e: any) {
    cfgErr.value = e?.message || '保存失败'
  }
}
</script>

<template>
  <div class="main settings">
    <div class="settings-hd">
      <h2>设置</h2>
      <span class="settings-sub">Settings</span>
    </div>
    <div class="settings-body">
      <div class="settings-card">
        <h3>账号信息</h3>
        <div class="setting-row">
          <span class="label">用户名</span>
          <span>{{ user?.username || '—' }}</span>
        </div>
        <div class="setting-row">
          <span class="label">显示名</span>
          <span>{{ user?.display_name || '—' }}</span>
        </div>
        <div class="setting-row">
          <span class="label">角色</span>
          <span>{{ user?.role || '—' }}</span>
        </div>
        <button class="logout-btn" @click="doLogout" title="登录">🚪 退出登录</button>
      </div>

      <div class="settings-card" style="margin-top:16px">
        <h3>修改密码</h3>
        <div class="pwd-row">
          <span class="label">原密码</span>
          <input v-model="oldPwd" type="password" class="pwd-input" placeholder="原密码" />
        </div>
        <div class="pwd-row">
          <span class="label">新密码</span>
          <input v-model="newPwd" type="password" class="pwd-input" placeholder="新密码(至少4位)" @keyup.enter="doChangePwd" />
        </div>
        <p v-if="pwdErr" class="pwd-err">{{ pwdErr }}</p>
        <p v-if="pwdMsg" class="pwd-ok">{{ pwdMsg }}</p>
        <button class="pwd-btn" @click="doChangePwd" title="修改密码">🔑 修改密码</button>
      </div>

      <div class="settings-card" style="margin-top:16px;max-width:520px">
        <h3>🤖 模型配置(统一)</h3>
        <p class="cfg-hint">各工具(设计对话 / 手绘识别 / 语音)统一使用你的配置;留空则用系统默认</p>
        <div class="cfg-tabs">
          <button class="cfg-tab" :class="{ active: cfgTab === 'inference' }" @click="cfgTab = 'inference'" title="推理">推理</button>
          <button class="cfg-tab" :class="{ active: cfgTab === 'vision' }" @click="cfgTab = 'vision'" title="视觉">视觉</button>
          <button class="cfg-tab" :class="{ active: cfgTab === 'voice' }" @click="cfgTab = 'voice'" title="语音">语音</button>
        </div>
        <div class="cfg-row">
          <span class="label">说明</span>
          <span>{{ KIND_LABEL[cfgTab] }}</span>
        </div>
        <div class="cfg-row">
          <span class="label">地址</span>
          <input v-model="modelCfg[cfgTab].base_url" class="pwd-input cfg-input" placeholder="https://open.bigmodel.cn/api/paas/v4" />
        </div>
        <div class="cfg-row">
          <span class="label">API Key</span>
          <input v-model="modelCfg[cfgTab].api_key" type="password" class="pwd-input cfg-input" placeholder="智谱 API Key" />
        </div>
        <div class="cfg-row">
          <span class="label">模型</span>
          <input v-model="modelCfg[cfgTab].model" class="pwd-input cfg-input" :placeholder="cfgTab === 'inference' ? 'glm-4.5-flash' : cfgTab === 'vision' ? 'glm-4.5v' : 'glm-4.5-flash'" />
        </div>
        <p v-if="cfgErr" class="pwd-err">{{ cfgErr }}</p>
        <p v-if="cfgMsg" class="pwd-ok">{{ cfgMsg }}</p>
        <button class="pwd-btn" @click="saveModelConfig" :disabled="cfgLoading" title="保存">{{ cfgLoading ? '加载中...' : '💾 保存模型配置' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.main{flex:1;display:flex;flex-direction:column;min-width:0;background:#fff}
.settings-hd{display:flex;align-items:center;padding:0 20px;height:48px;border-bottom:1px solid #e5e5e5;flex-shrink:0;gap:8px}
.settings-hd h2{font-size:13px;font-weight:600;color:#111}
.settings-sub{font-size:10px;color:#999;background:#f3f4f6;padding:2px 8px;border-radius:6px}
.settings-body{flex:1;overflow-y:auto;padding:24px}
.settings-card{max-width:400px;background:#fafafa;border:1px solid #e5e5e5;border-radius:12px;padding:20px}
.settings-card h3{font-size:14px;font-weight:600;margin-bottom:16px;color:#333}
.setting-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;font-size:13px;border-bottom:1px solid #f0f0f0}
.setting-row .label{color:#999}
.logout-btn{margin-top:16px;background:#fee2e2;color:#dc2626;border:1px solid #fecaca;border-radius:6px;padding:8px 16px;font-size:13px;cursor:pointer}
.logout-btn:hover{background:#fecaca}
.pwd-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;font-size:13px}
.pwd-row .label{color:#999}
.pwd-input{border:1px solid #d0d0d4;border-radius:6px;padding:5px 10px;font-size:13px;width:200px}
.pwd-btn{margin-top:12px;background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:13px;cursor:pointer}
.pwd-err{color:#dc2626;font-size:12px;margin:6px 0 0}
.pwd-ok{color:#059669;font-size:12px;margin:6px 0 0}
.cfg-hint{font-size:12px;color:#888;margin-bottom:10px}
.cfg-tabs{display:flex;gap:6px;margin-bottom:12px}
.cfg-tab{background:#f3f4f6;border:1px solid #e5e5e5;border-radius:6px;padding:4px 14px;font-size:12px;cursor:pointer;color:#555}
.cfg-tab.active{background:#e0e7ff;color:#4f46e5;font-weight:600;border-color:#4f46e5}
.cfg-row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;font-size:13px}
.cfg-row .label{color:#999;flex-shrink:0;width:70px}
.cfg-input{width:340px}
</style>
