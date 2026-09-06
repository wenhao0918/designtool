<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'
import SketchPad from '@/components/SketchPad.vue'
import PrimitivePicker from '@/components/PrimitivePicker.vue'
import GanttChart from '@/components/GanttChart.vue'
import MaterialQuery from '@/components/MaterialQuery.vue'
import OcrTool from '@/components/OcrTool.vue'
import DraftUpload from '@/components/DraftUpload.vue'

defineOptions({ name: 'ToolsView' })

const props = defineProps<{ project: string; tool: string }>()
const emit = defineEmits<{ (e: 'navigate', view: string): void }>()
const store = useAppStore()
const sketchSent = ref('')

function onSketchSent(message: string) {
  sketchSent.value = message
  emit('navigate', 'design')
  store.send(message)
}

async function onGanttSavedAs(name: string) {
  await store.loadProjects()
  await store.selectProject(name)
}
</script>

<template>
  <div class="main tools">
    <div v-show="props.tool === 'sketch'" style="flex:1;display:flex;flex-direction:column;min-height:0">
      <SketchPad
        :project="props.project || store.current"
        embed
        @sent="onSketchSent"
        @close="emit('navigate', 'design')"
      />
    </div>
    <div v-show="props.tool === 'primitives'" class="tools-body">
      <PrimitivePicker />
    </div>
    <div v-show="props.tool === 'gantt'" class="tools-body">
      <GanttChart :project="props.project || store.current" @saved-as="onGanttSavedAs" />
    </div>
    <div v-show="props.tool === 'material'" class="tools-body">
      <MaterialQuery />
    </div>
    <div v-show="props.tool === 'ocr'" class="tools-body">
      <OcrTool />
    </div>
    <div v-show="props.tool === 'draft'" class="tools-body">
      <DraftUpload />
    </div>
    <div v-show="props.tool !== 'sketch' && props.tool !== 'primitives' && props.tool !== 'gantt' && props.tool !== 'material' && props.tool !== 'ocr' && props.tool !== 'draft'" class="body-empty">
      <div class="body-empty-icon">🧰</div>
      <p>从左侧选择一个工具</p>
    </div>
  </div>
</template>

<style scoped>
.main{flex:1;display:flex;flex-direction:column;min-width:0;background:#fff}
.tools-body{flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden;padding:12px}
.body-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#999;gap:8px}
.body-empty-icon{font-size:44px}
.body-empty p{font-size:14px}
</style>
