<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import { onActivated } from 'vue'
import TopBar from '@/components/TopBar.vue'
import ChatArea from '@/components/ChatArea.vue'
import InputArea from '@/components/InputArea.vue'
import DocPanel from '@/components/DocPanel.vue'
import RulesPanel from '@/components/RulesPanel.vue'
import FilesPanel from '@/components/FilesPanel.vue'
import Viewer3D from '@/components/Viewer3D.vue'

defineOptions({ name: 'DesignView' })

const store = useAppStore()
defineEmits<{ (e: 'goto-sketch'): void }>()

// KeepAlive 缓存下,切回设计页时恢复进行中/刚结束的任务(切走再回来设计不丢)
onActivated(async () => {
  await store.restoreTaskState()
})
</script>

<template>
  <div class="design-wrap">
    <div v-if="store.current" class="main">
      <TopBar />
      <ChatArea />
      <InputArea @goto-sketch="$emit('goto-sketch')" />
    </div>
    <div v-else class="empty">
      <h2>Anvil</h2>
      <p>Select a project to start designing</p>
    </div>
    <Viewer3D />
    <DocPanel v-if="store.docOpen" />
    <RulesPanel v-if="store.rulesVisible" />
    <FilesPanel v-if="store.filesOpen" />
  </div>
</template>

<style scoped>
.design-wrap{flex:1;position:relative;min-width:0;min-height:0}
.main{height:100%;display:flex;flex-direction:column;min-width:0;background:#fff}
.empty{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#999}
.empty h2{font-size:24px;font-weight:300;margin-bottom:8px}
</style>
