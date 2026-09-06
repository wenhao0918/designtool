<template>
  <div class="sketch-pad" :class="props.embed ? 'embed' : 'fullscreen'">
    <!-- 工具栏 -->
    <div class="sketch-toolbar">
      <!-- 模式工具组（互斥） -->
      <div class="tool-group">
        <button class="sk-btn" :class="{ active: toolMode === 'pen' }" @click="switchPen" title="手绘草图">✏️ 绘画</button>
        <button class="sk-btn" title="选择/编辑" :class="{ active: toolMode === 'select' }" @click="toggleSelect">{{ toolMode === 'select' ? (selectMode === 'lasso' ? '🌀 圈选' : '🔲 框选') : '🔲 选择' }}</button>
        <button class="sk-btn" :class="{ active: toolMode === 'pan' }" @click="switchTool('pan')" title="✋移动画布">✋ 移动画布</button>
      </div>
      <div class="tool-group">
        <button class="sk-btn" :class="{ active: toolMode === 'eraser' }" @click="switchTool('eraser')" title="🧽橡皮">🧽 橡皮</button>
      </div>
      <!-- 形状工具 -->
      <div class="shape-picker" title="形状工具">
        <button class="sk-btn" :class="{ active: toolMode === 'shape' && shapeType === 'rect' }" @click="setShape('rect')" title="矩形">▭</button>
        <button class="sk-btn" :class="{ active: toolMode === 'shape' && shapeType === 'ellipse' }" @click="setShape('ellipse')" title="圆形/椭圆">◯</button>
        <button class="sk-btn" :class="{ active: toolMode === 'shape' && shapeType === 'polygon' }" @click="setShape('polygon')" title="多边形">⬠</button>
        <button class="sk-btn" :class="{ active: toolMode === 'shape' && shapeType === 'lasso' }" @click="setShape('lasso')" title="自由圈选（自动封闭）">🌀</button>
      </div>
      <select class="sk-select" v-model="compCategory" @change="onCompCategoryChange">
        <option value="">＋ 添加形状</option>
        <option value="mechanical">🔧 机械组件</option>
        <option value="2d">📐 平面几何</option>
        <option value="3d">📦 立体几何</option>
      </select>
      <button class="sk-btn" :class="{ recording: listening }" @click="toggleVoice" title="按住录音转文字">
        {{ listening ? '🔴 录音中...' : '🎤 语音' }}
      </button>
      <!-- 笔触选择 -->
      <div class="brush-picker" title="笔触">
        <button v-for="b in BRUSHES" :key="b.id" class="brush-item"
          :class="{ active: brushId === b.id }"
          @click="brushId = b.id" :title="b.name">
          {{ b.icon }}
        </button>
      </div>
      <!-- 线宽调节 -->
      <div class="width-control" title="线条粗细">
        <span class="width-icon">粗细</span>
        <input type="range" min="0.5" max="3" step="0.1" v-model="widthScale" class="width-slider" />
        <span class="width-val">{{ Math.round(widthScale * 100) }}%</span>
      </div>
      <!-- 调色板：颜色 = 意图语义 + 任意色 -->
      <div class="palette">
        <div v-for="c in PALETTE" :key="c.color" class="pal-item"
          :class="{ active: penColor === c.color && !isCustomColor }"
          :style="{ background: c.color }"
          :title="c.name + '：' + c.desc"
          @click="pickPaletteColor(c.color)"></div>
        <!-- 任意色取色器 -->
        <div class="pal-custom" :style="{ background: isCustomColor ? penColor : 'conic-gradient(red, yellow, lime, cyan, blue, magenta, red)' }"
          :class="{ active: isCustomColor }" title="自定义任意颜色">
          <input type="color" v-model="customColor" class="pal-color-input" @input="useCustomColor" />
        </div>
      </div>
      <span class="pen-label">{{ currentColorName }}</span>
      <span class="sk-spacer"></span>
      <!-- AI 设计层缩放 -->
      <span class="zoom-label">设计层</span>
      <button class="sk-btn" @click="zoomOut" title="－">－</button>
      <input type="range" class="zoom-slider" min="30" max="400" step="5"
        :value="Math.round(zoom * 100)" @input="onZoomSlider" title="拖动连续缩放" />
      <button class="sk-btn" @click="zoomIn" title="新建">＋</button>
      <span class="zoom-val">{{ Math.round(zoom * 100) }}%</span>
      <button class="sk-btn" @click="zoomReset" title="重置视图">⤢</button>
      <button class="sk-btn" @click="undo" title="撤销共享">↩ 撤销</button>
      <button class="sk-btn" @click="clear" title="清除输入">🗑 清空</button>
      <button class="sk-btn" @click="newSketch" title="新建空白画布">📄 新建</button>
      <button class="sk-btn" @click="restoreSketch" title="从缓存重绘">🔄 重绘</button>
      <button class="sk-btn" @click="toggleWriting" :class="{ active: writingMode }" title="书写模式：多笔自动归为一个便签对象，可整体拖动/缩放/Del删除">✍️ 书写</button>
      <button class="sk-btn" @click="saveSketch" title="保存到本地缓存">💾 保存</button>
      <button class="sk-btn" @click="clearAllShapes" title="清除所有已放置的组件（笔迹保留）">🗑 清组件</button>
      <button class="sk-btn" @click="$emit('close')" title="✕">✕</button>
      <button class="sk-btn" @click="showLLMSettings = !showLLMSettings" :class="{ active: showLLMSettings }" title="⚙️LLM">⚙️ LLM</button>
      <button class="sk-btn sk-primary" title="发送给AI设计" @click="gotoDesign" :disabled="sending">
        {{ sending ? '处理中...' : '进入设计' }}
      </button>
    </div>

    <!-- 绘图标签栏 -->
    <div class="sketch-tabs">
      <div v-for="(d, i) in docs" :key="d.meta.createdAt" class="sketch-tab" :class="{ active: i === docIndex }" @click="switchToDoc(i)">
        <span class="sketch-tab-name">{{ d.meta.title || `绘图 ${i + 1}` }}</span>
        <button v-if="docs.length > 1" class="sketch-tab-close" @click.stop="closeTab(i)" title="关闭">×</button>
      </div>
      <button class="sketch-tab-add" @click="newSketch" title="新建绘图">＋</button>
    </div>

    <!-- LLM 设置面板 -->
    <div v-if="showLLMSettings" class="llm-settings">
      <div class="llm-section">
        <div class="llm-section-title">🧠 推理 LLM</div>
        <label>地址 <input class="sk-input" v-model="llmSettings.inference.baseUrl" placeholder="https://api.deepseek.com/v1" style="width:180px" /></label>
        <label>Key <input class="sk-input" v-model="llmSettings.inference.apiKey" placeholder="sk-..." style="width:160px" /></label>
        <label>模型 <input class="sk-input" v-model="llmSettings.inference.model" placeholder="deepseek-chat" style="width:120px" /></label>
      </div>
      <div class="llm-section">
        <div class="llm-section-title">👁️ Vision LLM</div>
        <label>地址 <input class="sk-input" v-model="llmSettings.vision.baseUrl" placeholder="https://api.moonshot.cn/v1" style="width:180px" /></label>
        <label>Key <input class="sk-input" v-model="llmSettings.vision.apiKey" placeholder="sk-..." style="width:160px" /></label>
        <label>模型 <input class="sk-input" v-model="llmSettings.vision.model" placeholder="moonshot-v1-128k-vision-preview" style="width:160px" /></label>
      </div>
    </div>

    <!-- 组件面板（按分类切换） -->
    <div v-if="compCategory" class="comp-panel">
      <div class="comp-panel-title">{{ compCategoryLabel }} → 点击放置到设计层</div>
      <div class="comp-grid">
        <div v-for="s in currentShapes" :key="s.type" class="comp-item" :class="{ active: compCategory === '3d' ? threeDPlacing === s.type : placing === s.type }" @click="startPlacing(s.type)">
          <span class="comp-icon">{{ s.icon }}</span>
          <span class="comp-name">{{ s.name }}</span>
        </div>
      </div>
    </div>
    <div v-if="placing && TWO_D_SIZED.has(placing) && !placeAnchor" class="comp-hint">① 点击画布定「{{ compName(placing) }}」中心，ESC 取消</div>
    <div v-if="placing && TWO_D_SIZED.has(placing) && placeAnchor" class="comp-hint">② 移动鼠标实时预览，点击第二点结束画图，ESC 取消</div>
    <div v-if="placing && !TWO_D_SIZED.has(placing)" class="comp-hint">放置中：点击画布放下「{{ compName(placing) }}」，ESC 取消</div>
    <div v-if="threeDPlacing === 'cuboid' && cuboidPhase === 1" class="comp-hint">① 横划定义「长方体」正面长度，ESC 取消</div>
    <div v-if="threeDPlacing === 'cuboid' && cuboidPhase === 2" class="comp-hint">② 竖划定义「长方体」正面高度，ESC 取消</div>
    <div v-if="threeDPlacing === 'cuboid' && cuboidPhase === 3" class="comp-hint">③ 斜划定义「长方体」宽度和角度，ESC 取消</div>
    <div v-if="threeDPlacing === 'cylinder' && cylinderPhase === 1" class="comp-hint">① 拖拽定义「圆柱」底面直径，ESC 取消</div>
    <div v-if="threeDPlacing === 'cylinder' && cylinderPhase === 2" class="comp-hint">② 拖拽定义「圆柱」高度，ESC 取消</div>
    <div v-if="threeDPlacing === 'cone' && conePhase === 1" class="comp-hint">① 拖拽定义「圆锥」底面直径，ESC 取消</div>
    <div v-if="threeDPlacing === 'cone' && conePhase === 2" class="comp-hint">② 拖拽定义「圆锥」顶点方向和高度，ESC 取消</div>
    <div v-if="threeDPlacing === 'rcone'" class="comp-hint">一笔画「正圆锥」：起点为顶点，拖出斜棱，终点定底面半径与高度，ESC 取消</div>
    <div v-if="threeDPlacing && threeDPlacing !== 'cuboid' && threeDPlacing !== 'cylinder' && threeDPlacing !== 'cone' && threeDPlacing !== 'rcone' && threeDPlacing !== 'text'" class="comp-hint">拖拽画线定义「{{ compName(threeDPlacing) }}」的边长和方向，ESC 取消</div>
    <div v-if="threeDPlacing === 'text'" class="comp-hint">文字：点击画布放置，ESC 取消</div>
    <div v-if="threeDPlacing === 'text'" class="text-settings">
      <label>字体 <input class="sk-input" v-model="textSettings.font" style="width:120px" title="CSS font 如 16px sans-serif" /></label>
      <label>颜色 <input type="color" v-model="textSettings.color" style="width:30px;padding:0" /></label>
    </div>
    <div v-if="selecting" class="comp-hint">{{ selectMode === 'lasso' ? '自由圈选中：拖动画出选择区域，松手自动闭合' : '框选中：拖拽选择设计层区域' }}</div>
    <div v-if="toolMode === 'pan' && !panning" class="comp-hint">拖拽移动画布视图</div>
    <div v-if="writingMode" class="comp-hint" style="background:#fefce8;color:#a16207;border-bottom:1px solid #fde68a">✍️ 书写中：多笔自动归为一个便签，点击「书写」或按 ESC 完成</div>

    <!-- 对象属性编辑面板（选中对象时显示） -->
    <div v-if="editingPose && selectedIds.length > 0" class="pose-panel">
      <div class="pose-panel-title">📐 位姿（{{ selectedIds.length }} 个对象）</div>
      <div class="pose-grid">
        <label>X <input type="number" class="sk-input" :value="editingPose.x" @input="onPoseInput('x', Number(($event.target as HTMLInputElement).value))" style="width:70px" step="any" /></label>
        <label>Y <input type="number" class="sk-input" :value="editingPose.y" @input="onPoseInput('y', Number(($event.target as HTMLInputElement).value))" style="width:70px" step="any" /></label>
        <label>Z <input type="number" class="sk-input" :value="editingPose.z" @input="onPoseInput('z', Number(($event.target as HTMLInputElement).value))" style="width:70px" step="any" /></label>
        <label>A° <input type="number" class="sk-input" :value="editingPose.a" @input="onPoseInput('a', Number(($event.target as HTMLInputElement).value))" style="width:60px" step="any" /></label>
        <label>B° <input type="number" class="sk-input" :value="editingPose.b" @input="onPoseInput('b', Number(($event.target as HTMLInputElement).value))" style="width:60px" step="any" /></label>
        <label>C° <input type="number" class="sk-input" :value="editingPose.c" @input="onPoseInput('c', Number(($event.target as HTMLInputElement).value))" style="width:60px" step="any" /></label>
      </div>
    </div>

    <!-- 图层面板 -->
    <div class="layer-panel">
      <div class="layer-panel-hd">
        <span class="layer-panel-title">📑 图层</span>
        <button class="sk-btn" @click="addLayer" title="新建图层">＋</button>
      </div>
      <div v-for="l in layers" :key="l.id" class="layer-row" :class="{ active: l.id === activeLayerId }" @click="selectLayer(l.id)">
        <button class="layer-eye" :class="{ off: !l.visible }" @click.stop="toggleLayer(l.id)" :title="l.visible ? '隐藏' : '显示'">
          {{ l.visible ? '👁' : '—' }}
        </button>
        <span class="layer-name" :contenteditable="l.id === activeLayerId" @blur="renameLayer(l.id, ($event.target as HTMLElement).innerText)">{{ l.name }}</span>
        <span class="layer-count">{{ l.strokes.length }}笔</span>
        <button v-if="layers.length > 1" class="layer-del" @click.stop="deleteLayer(l.id)" title="删除图层">×</button>
      </div>
    </div>

    <div v-if="voiceText" class="sketch-voicetext">🗣️ {{ voiceText }}</div>

    <!-- 双层画布 -->
    <div class="sketch-canvas-wrap">
      <!-- 拖拽提示浮层（固定于画布左下角） -->
      <div v-if="isDragging" class="drag-tooltip">
        <div class="drag-tt-row">📍 X: {{ dragInfo.x }} &nbsp; Y: {{ dragInfo.y }}</div>
        <div class="drag-tt-row">↗ ΔX: {{ dragInfo.dx }} &nbsp; ΔY: {{ dragInfo.dy }}</div>
        <div class="drag-tt-row">📐 A:{{ dragInfo.a }}° B:{{ dragInfo.b }}° C:{{ dragInfo.c }}°</div>
      </div>
      <!-- 缩放容器：设计层 + 表达层一起缩放 -->
      <div class="zoom-layer" :style="{ transform: `translate(${panX}px,${panY}px) scale(${zoom})`, transformOrigin: '0 0', cursor: toolMode === 'pan' ? (panning ? 'grabbing' : 'grab') : undefined }">
        <div class="design-layer">
          <canvas ref="designCanvas" class="design-canvas"></canvas>
        </div>
        <canvas ref="sketchCanvas" class="sketch-canvas"
          @pointerdown="onPointerDown" @pointermove="onPointerMove"
          @pointerup="onPointerUp" @pointerleave="onPointerUp"
          @wheel.prevent="onWheel"></canvas>
        <canvas ref="previewCanvas" class="preview-canvas"></canvas>
        <div v-if="placing" ref="ghostEl" class="comp-ghost">{{ compIcon(placing) }}</div>
        <div v-if="selRect" class="sel-box" :style="selRectStyle"></div>
      </div>

      <!-- 比例尺（不缩放，固定位置） -->
      <div class="scale-bar">
        <div class="scale-bar-line"></div>
        <span class="scale-bar-label">{{ scaleBarLabel }}</span>
        <span class="scale-bar-ratio">1:{{ Math.round(zoom >= 1 ? zoom : 1 / (1/zoom)) }}</span>
      </div>
      <!-- 提示 -->
      <div v-if="!hasInk && !hasDesign && !sending" class="sketch-hint">
        画笔绘图 | 形状放置 | 组件标注 | 语音输入<br />
        滚轮缩放 | 画完点「发送给AI」识别设计意图
      </div>
    </div>

    <!-- AI 对话输入条 -->
    <div class="ai-chat">
      <div class="ai-chat-input">
        <input v-model="chatInput" placeholder="与 AI 对话：描述意图、提问、修改（回车发送）" @keydown.enter.prevent="sendChat" :disabled="chatSending" />
        <button class="sk-btn sk-primary" @click="sendChat" :disabled="chatSending || !chatInput.trim()" title="发送消息">{{ chatSending ? '...' : '发送' }}</button>
        <button v-if="chatMessages.length" class="sk-btn" @click="chatOpen = !chatOpen">{{ chatOpen ? '收起对话' : '💬 对话' }}</button>
      </div>
    </div>

    <!-- AI 回复弹框 -->
    <div v-if="chatOpen" class="ai-modal">
      <div class="ai-modal-box">
        <div class="ai-modal-hd">
          <span class="ai-modal-title">🤖 AI 回复</span>
          <button class="ai-modal-close" @click="chatOpen = false" title="✕">✕</button>
        </div>
        <div class="ai-modal-body" ref="chatHistoryEl">
          <div v-if="!chatMessages.length" class="ai-chat-empty">与 AI 对话：描述设计意图、提问、要求修改</div>
          <div v-for="(m, i) in chatMessages" :key="i" class="ai-msg" :class="m.role">
            <span class="ai-msg-label">{{ m.role === 'user' ? '你' : 'AI' }}</span>
            <span class="ai-msg-text">{{ m.content }}</span>
          </div>
          <div v-if="chatSending" class="ai-msg assistant"><span class="ai-msg-label">AI</span><span class="ai-msg-text">思考中...</span></div>
        </div>
      </div>
    </div>

    <!-- AI 解读：右侧面板 -->
    <div class="interp-panel" :class="{ collapsed: interpCollapsed }" :style="{ width: interpWidth + 'px' }" 
      @pointermove="onResizePointerMove" @pointerup="onResizePointerUp" @pointerleave="onResizePointerUp">
      <div class="interp-resize-handle" @pointerdown.prevent="onResizePointerDown"></div>
      <div class="interp-panel-hd">
        <span class="interp-panel-title">🔍 AI 解读</span>
        <button class="sk-btn" :class="{ 'sk-primary': interpMode === 'structure' }" @click="switchInterpretMode('structure')" :disabled="interpreting" style="font-size:11px;padding:3px 8px" title="结构解读">📊 结构</button>
        <button class="sk-btn" :class="{ 'sk-primary': interpMode === 'vision' }" @click="switchInterpretMode('vision')" :disabled="interpreting" style="font-size:11px;padding:3px 8px" title="图像识别">🖼️ 图像</button>
        <button class="interp-toggle-btn" @click="interpCollapsed = !interpCollapsed" :title="interpCollapsed ? '展开面板' : '折叠面板'">{{ interpCollapsed ? '◁' : '▷' }}</button>
      </div>
      <div class="interp-panel-body" ref="interpBodyEl">
        <div v-if="components.length > 0 && interpMessages.length === 0 && !interpreting" class="comp-hint" style="background:#fef3c7;color:#92400e;border-bottom:1px solid #fcd34d;margin-bottom:4px">
          ⚠️ 当前有 {{ components.length }} 个已放置组件。如需清除旧组件保留笔迹，点工具栏「🗑 清组件」
        </div>
        <div v-if="interpMessages.length === 0 && !interpreting && !followupStreaming" class="ai-chat-empty">输入问题，按回车让 AI 解读画布内容</div>
        <div v-if="interpreting && interpMessages.length === 0 && !followupStreaming" class="interp-loading">
          <div class="interp-spinner"></div>
          <span>{{ interpMode === 'structure' ? '正在分析结构...' : '正在识别图像...' }}</span>
        </div>
        <div v-for="(m, i) in interpMessages" :key="i" class="ai-msg" :class="m.role">
          <span class="ai-msg-label">{{ m.role === 'user' ? '你' : 'AI' }}</span>
          <span class="ai-msg-text" v-html="renderMarkdown(m.content)"></span>
        </div>
        <div v-if="followupStreaming && streamingContent" class="ai-msg assistant">
          <span class="ai-msg-label">AI</span>
          <span class="ai-msg-text" v-html="renderMarkdown(streamingContent)"></span>
          <span class="typing-cursor">▊</span>
        </div>
        <div v-if="followupStreaming && !streamingContent" class="interp-loading">
          <div class="interp-spinner"></div>
          <span>思考中...</span>
        </div>
      </div>
      <div class="interp-panel-input">
        <input v-model="followupInput" :placeholder="interpMessages.length ? '追问...' : '回车解读画布，也可输入问题...'" @keydown.enter="sendOrStartInterpret" :disabled="interpreting || followupStreaming" />
        <button class="sk-btn sk-primary" @click="sendOrStartInterpret" :disabled="interpreting || followupStreaming" title="发送消息">发送</button>
      </div>
    </div>

    <div v-if="errorMsg" class="sketch-error">{{ errorMsg }}</div>

    <!-- 保存命名弹窗 -->
    <div v-if="savePromptVisible" class="save-overlay" @click.self="cancelSave">
      <div class="save-dialog">
        <div class="save-dialog-title">💾 保存绘图</div>
        <input v-model="saveName" class="save-input" placeholder="输入文件名..." @keydown.enter="confirmSave" autofocus />
        <div class="save-btns">
          <button class="sk-btn sk-primary" @click="confirmSave" title="保存">保存</button>
          <button class="sk-btn" @click="cancelSave" title="取消">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick, reactive } from 'vue'
import { sendMessage, apiRaw } from '../api'
import { myTools } from '@/api'
import { recognizeGesture, type Point } from '../utils/gesture'
import { createDocument, docToCacheV2, migrateV1toV2, SCENES, strokeBBox, nextObjectId, type SketchDocument, type SketchLayer, type StrokeData as StrokeDataType, type SketchScene, type DesignObject } from '../types/sketch'
import { useAppStore } from '../stores/app'

const store = useAppStore()

// 手势可视化标记（画在表达层，表示"这里有个手势"）
const GESTURE_META: Record<string, { label: string; color: string }> = {
  confirm: { label: '✓确认', color: '#059669' },
  reject: { label: '✕否定', color: '#dc2626' },
  select: { label: '○圈选', color: '#4a7dff' },
  point: { label: '→指向', color: '#7c3aed' },
  erase: { label: '~~~~擦除', color: '#f59e0b' },
  emphasize: { label: '=强调', color: '#0891b2' },
  rotate: { label: '⟳旋转', color: '#db2777' },
  move: { label: '↔移动', color: '#ea580c' },
}
const gestures = ref<{ gesture: string; x: number; y: number; note: string }[]>([])
let currentStroke: Point[] = []  // 当前笔画轨迹（用于手势识别）

// === 调色板：颜色 = 意图语义 ===
const PALETTE = [
  { color: '#dc2626', name: '红·问题', desc: '错误/否定/要改' },
  { color: '#059669', name: '绿·确认', desc: 'OK/通过/保留' },
  { color: '#2563eb', name: '蓝·建议', desc: '建议改成这样' },
  { color: '#d97706', name: '黄·注意', desc: '小心/警告' },
  { color: '#7c3aed', name: '紫·疑问', desc: '这里什么意思' },
  { color: '#111827', name: '黑·中性', desc: '普通注释' },
]
const penColor = ref('#dc2626')  // 当前画笔颜色（默认红=问题）
const customColor = ref('#333333')  // 自定义任意色
const isCustomColor = ref(false)    // 是否正在用自定义色

// === 笔触系统 ===
interface BrushDef {
  id: string
  name: string
  icon: string
  widthMin: number   // 最小线宽
  widthMax: number   // 最大线宽（随压力）
  alpha: number      // 透明度
  cap: CanvasLineCap // 线帽
}
const BRUSHES: BrushDef[] = [
  { id: 'pen', name: '圆头笔', icon: '✒️', widthMin: 1.5, widthMax: 5, alpha: 1, cap: 'round' },
  { id: 'pencil', name: '铅笔', icon: '✏️', widthMin: 0.6, widthMax: 2, alpha: 0.65, cap: 'round' },
  { id: 'marker', name: '马克笔', icon: '🖊️', widthMin: 4, widthMax: 8, alpha: 0.45, cap: 'square' },
  { id: 'calligraphy', name: '书法笔', icon: '🖌️', widthMin: 0.5, widthMax: 7, alpha: 1, cap: 'round' },
  { id: 'highlighter', name: '荧光笔', icon: '🖍️', widthMin: 8, widthMax: 12, alpha: 0.3, cap: 'square' },
]
const brushId = ref('pen')
const currentBrush = computed(() => BRUSHES.find(b => b.id === brushId.value) || BRUSHES[0])
const widthScale = ref(1)  // 线宽倍率 0.5x ~ 3x

// === 画笔设置持久化：笔触/线宽/颜色 保存到 localStorage，刷新自动恢复 ===
const COMP_KEY = 'anvil_sketch_comp'
const BRUSH_KEY = 'anvil_sketch_brush'
interface BrushSettings { brushId: string; widthScale: number; penColor: string; customColor: string; isCustomColor: boolean }
function loadBrushSettings() {
  try {
    const s: BrushSettings = JSON.parse(localStorage.getItem(BRUSH_KEY) || 'null')
    if (!s) return
    if (BRUSHES.some(b => b.id === s.brushId)) brushId.value = s.brushId
    if (typeof s.widthScale === 'number' && s.widthScale >= 0.5 && s.widthScale <= 3) widthScale.value = s.widthScale
    if (typeof s.penColor === 'string' && /^#/.test(s.penColor)) penColor.value = s.penColor
    if (typeof s.customColor === 'string' && /^#/.test(s.customColor)) customColor.value = s.customColor
    isCustomColor.value = !!s.isCustomColor
  } catch {}
}
function saveBrushSettings() {
  try {
    const s: BrushSettings = {
      brushId: brushId.value,
      widthScale: widthScale.value,
      penColor: penColor.value,
      customColor: customColor.value,
      isCustomColor: isCustomColor.value,
    }
    localStorage.setItem(BRUSH_KEY, JSON.stringify(s))
  } catch {}
}
// 监听变化自动保存
watch([brushId, widthScale, penColor, customColor, isCustomColor], saveBrushSettings)

// 根据压力和笔触算线宽（叠加用户粗细倍率）
function brushWidth(pressure: number): number {
  const b = currentBrush.value
  const base = b.widthMin + (b.widthMax - b.widthMin) * Math.max(0.1, Math.min(1, pressure))
  return base * widthScale.value
}

function useCustomColor() {
  isCustomColor.value = true
  penColor.value = customColor.value
}

const currentColorName = computed(() => {
  if (isCustomColor.value) return '自定义'
  return PALETTE.find(c => c.color === penColor.value)?.name || ''
})

// 点击语义色时退出自定义模式
function pickPaletteColor(color: string) {
  isCustomColor.value = false
  penColor.value = color
}

const props = defineProps<{ project: string; embed?: boolean }>()
const emit = defineEmits<{ (e: 'sent', message: string): void; (e: 'close'): void }>()

// === AI 对话 ===
const chatInput = ref('')
const chatSending = ref(false)
const chatOpen = ref(false)
const chatMessages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
const chatHistoryEl = ref<HTMLDivElement | null>(null)

async function sendChat() {
  const text = chatInput.value.trim()
  if (!text || chatSending.value) return

  // 形状命令：文字定义图形 → 回车后放置，或文字直接指定位置
  const shapeCmd = parseShapeCommand(text)
  if (shapeCmd) {
    chatInput.value = ''
    chatMessages.value.push({ role: 'user', content: text })
    chatMessages.value.push({ role: 'assistant', content: shapeCmd.msg })
    chatOpen.value = true
    scrollChat()
    if (shapeCmd.x !== undefined && shapeCmd.y !== undefined && dctx) {
      // 文字指定了坐标（表达层坐标）→ 转换到设计层坐标直接放置
      const dx = (shapeCmd.x - panX.value) / zoom.value
      const dy = (shapeCmd.y - panY.value) / zoom.value
      const s = ALL_SHAPES.find(s => s.type === shapeCmd.type)
      if (s && s.category === '3d') {
        const sz = shapeCmd.size || 100
        components.value.push({ type: shapeCmd.type, x: dx, y: dy, size: sz })
        draw3DShape(dctx, shapeCmd.type, dx, dy, sz, 0)
      } else {
        components.value.push({ type: shapeCmd.type, x: dx, y: dy })
        drawComponent(dctx, shapeCmd.type, dx, dy)
      }
      redrawStrokes()
      scheduleAutoSave()
    } else {
      // 进入放置/拖拽模式
      startPlacing(shapeCmd.type)
    }
    return
  }

  // 正常 AI 对话
  chatOpen.value = true
  if (!props.project) {
    // 没有项目 → 自动创建一个
    const name = `sketch_${new Date().toISOString().slice(0, 10)}_${Math.random().toString(36).slice(2, 6)}`
    await store.doCreateProject(name)
    // 等待 props.project 被父组件更新
    await nextTick()
    if (!props.project) {
      chatMessages.value.push({ role: 'assistant', content: '⚠️ 自动创建项目失败，请先在左侧边栏手动创建' })
      scrollChat()
      return
    }
    chatMessages.value.push({ role: 'assistant', content: `📁 已自动创建项目「${name}」` })
  }
  chatInput.value = ''
  chatMessages.value.push({ role: 'user', content: text })
  chatSending.value = true
  scrollChat()
  try {
    const r = await sendMessage(props.project, text, [])
    if (!r.ok || !r.body) {
      const err = await r.text().catch(() => '')
      chatMessages.value.push({ role: 'assistant', content: '错误: HTTP ' + r.status + ' ' + err.slice(0, 100) })
      return
    }
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let reply = ''
    chatMessages.value.push({ role: 'assistant', content: '' })
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const lines = decoder.decode(value, { stream: true }).split('\n')
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const j = JSON.parse(line.slice(6))
          if (j.type === 'token') {
            reply += j.content || ''
            chatMessages.value[chatMessages.value.length - 1].content = reply
            scrollChat()
          } else if (j.type === 'step') {
            reply += '\n⚙️ ' + j.content
            chatMessages.value[chatMessages.value.length - 1].content = reply
          } else if (j.type === 'file') {
            reply += '\n📎 ' + j.content
            chatMessages.value[chatMessages.value.length - 1].content = reply
          } else if (j.type === 'error') {
            const tip = j.code === 'MODEL_NOT_CONFIGURED' ? '⚙️ ' + j.content + '\n（左侧栏「设置 → 模型配置」填入 API Key 保存后重试）' : j.content
            reply += '\n[错误] ' + tip
            chatMessages.value[chatMessages.value.length - 1].content = reply
          }
        } catch { /* 忽略非 JSON 行 */ }
      }
    }
    if (!reply) chatMessages.value.pop()
    scrollChat()
  } catch (e: any) {
    chatMessages.value.push({ role: 'assistant', content: '连接失败: ' + (e?.message || e) })
  } finally {
    chatSending.value = false
  }
}

function scrollChat() {
  nextTick(() => {
    if (chatHistoryEl.value) chatHistoryEl.value.scrollTop = chatHistoryEl.value.scrollHeight
  })
}

// === 状态 ===
const designCanvas = ref<HTMLCanvasElement | null>(null)
const sketchCanvas = ref<HTMLCanvasElement | null>(null)
const previewCanvas = ref<HTMLCanvasElement | null>(null)
const ghostEl = ref<HTMLDivElement | null>(null)
const sending = ref(false)
const errorMsg = ref('')
const hasInk = ref(false)      // 表达层有内容
const hasDesign = ref(false)   // 设计层有内容
const voiceText = ref('')
const listening = ref(false)
let recognition: any = null

// 工具模式
const toolMode = ref<'pen' | 'eraser' | 'select' | 'comp' | 'shape' | 'pan'>('pen')
// 组件选择持久化：HMR 不丢，刷新不丢
function loadCompSettings() {
  try {
    const s = JSON.parse(localStorage.getItem(COMP_KEY) || 'null')
    if (s) {
      if (s.compCategory && ['mechanical','2d','3d'].includes(s.compCategory)) compCategory.value = s.compCategory
      if (s.threeDPlacing && ALL_SHAPES.some(sh => sh.type === s.threeDPlacing)) threeDPlacing.value = s.threeDPlacing
    }
  } catch {}
}
function saveCompSettings() {
  try {
    localStorage.setItem(COMP_KEY, JSON.stringify({
      compCategory: compCategory.value,
      threeDPlacing: threeDPlacing.value,
    }))
  } catch {}
}
function loadCompCategoryLS(): string {
  try {
    const s = JSON.parse(localStorage.getItem(COMP_KEY) || 'null')
    return (s?.compCategory && ['mechanical','2d','3d'].includes(s.compCategory)) ? s.compCategory : ''
  } catch { return '' }
}
function loadThreeDPlacingLS(): string | null {
  try {
    const s = JSON.parse(localStorage.getItem(COMP_KEY) || 'null')
    return (s?.threeDPlacing && ALL_SHAPES.some(sh => sh.type === s.threeDPlacing)) ? s.threeDPlacing : null
  } catch { return null }
}
const compCategory = ref(loadCompCategoryLS())
const placing = ref<null | string>(null)
// 2d 组件两笔式放置：第一击定中心，移动出辅助线，第二击确认尺寸（ESC 取消锚点）
const placeAnchor = ref<{ x: number; y: number } | null>(null)
const TWO_D_SIZED = new Set(['circle', 'square', 'triangle', 'diamond', 'pentagon', 'hexagon'])
const threeDPlacing = ref<null | string>(loadThreeDPlacingLS())
// 组件选择变化自动持久化
watch([compCategory, threeDPlacing], saveCompSettings)
// 文字工具设置
const TEXT_KEY = 'anvil_sketch_text'
interface TextSettings { font: string; color: string }
function loadTextSettings(): TextSettings {
  try {
    const s = JSON.parse(localStorage.getItem(TEXT_KEY) || 'null')
    if (s && typeof s.font === 'string' && typeof s.color === 'string') return { font: s.font, color: s.color }
  } catch {}
  return { font: '16px sans-serif', color: '#111111' }
}
function saveTextSettings(s: TextSettings) {
  try { localStorage.setItem(TEXT_KEY, JSON.stringify(s)) } catch {}
}
const textSettings = ref(loadTextSettings())
watch(textSettings, s => saveTextSettings(s), { deep: true })

// 拖拽位置/方向实时显示
const dragInfo = reactive({ x: 0, y: 0, dx: 0, dy: 0, a: 0, b: 0, c: 0 })

// LLM 配置（推理 / Vision 分开，localStorage 持久化）
const LLM_KEY = 'anvil_sketch_llm'
interface LLMConfig { baseUrl: string; apiKey: string; model: string }
interface LLMSettings { inference: LLMConfig; vision: LLMConfig }
function loadLLMSettings(): LLMSettings {
  try {
    const s = JSON.parse(localStorage.getItem(LLM_KEY) || 'null')
    if (s && s.inference && s.vision) return s
  } catch {}
  return {
    inference: { baseUrl: 'https://api.deepseek.com/v1', apiKey: import.meta.env.VITE_LLM_INFERENCE_KEY ?? '', model: 'deepseek-v4-flash' },
    vision: { baseUrl: 'https://api.moonshot.cn/v1', apiKey: import.meta.env.VITE_LLM_VISION_KEY ?? '', model: 'moonshot-v1-128k-vision-preview' },
  }
}
const llmSettings = reactive(loadLLMSettings())
watch(() => ({ ...llmSettings }), v => { try { localStorage.setItem(LLM_KEY, JSON.stringify(v)) } catch {} }, { deep: true })
const showLLMSettings = ref(false)

// === 统一对象模型 ===
// 所有画布元素都是 DesignObject：笔划=对象，组件=对象，文字=对象
// 选中/移动/组合操作在对象层完成
const writingMode = ref(false)                             // 书写模式：多笔归为一个便签组
const objects = reactive<DesignObject[]>([])                // 全部对象列表
const selectedIds = ref<string[]>([])                           // 选中的对象 id 列表（ref 数组，模板响应式可靠）
let objDragStart: { x: number; y: number } | null = null    // 移动拖拽起点
const isDragging = ref(false)                                 // 是否正在拖拽（驱动模板）
let objDragOffsets: Map<string, { dx: number; dy: number }> = new Map()  // 各对象位移偏移
const currentGroupId = ref<string | null>(null)            // 当前书写便签的组 id
const selectedNoteId = ref<string | null>(null)            // 当前选中的便签组 id
interface NoteGroup { bbox: { x: number; y: number; w: number; h: number }; strokeIndices: number[] }
const noteGroups = new Map<string, NoteGroup>()            // groupId → 组信息（当前图层）
let noteScaleStart: { cx: number; cy: number; startDist: number } | null = null
const NOTE_PAD = 14                                        // 便签背景外扩
const NOTE_BG = 'rgba(255, 246, 213, 0.55)'                 // 便签底色
const NOTE_BORDER = '#e8c66a'                              // 便签边框

/** 从 components + strokes 重构整个 objects 列表（保留已有 id 与选中状态） */
function buildObjects() {
  const oldMap = new Map<string, DesignObject>()
  for (const o of objects) oldMap.set(o.id, o)

  const next: DesignObject[] = []

  // 组件 → 对象
  for (let i = 0; i < components.value.length; i++) {
    const c = components.value[i]
    // 计算包围盒
    let bx = c.x, by = c.y, bw = c.size || 44, bh = c.size || 44
    if (c.cylinderRadius) { bw = (c.cylinderRadius) * 2 + 20; bh = (c.size || 50) + 20; bx -= bw / 2; by -= bh }
    if (c.coneRadius) { bw = (c.coneRadius) * 2 + 20; bh = 100; bx -= bw / 2; by -= bh }
    if (c.cuboidVectors) {
      const pts = [
        { x: c.x, y: c.y },
        { x: c.x + c.cuboidVectors.frontTop.x, y: c.y + c.cuboidVectors.frontTop.y },
        { x: c.x + c.cuboidVectors.frontLeft.x, y: c.y + c.cuboidVectors.frontLeft.y },
        { x: c.x + c.cuboidVectors.frontTop.x + c.cuboidVectors.frontLeft.x, y: c.y + c.cuboidVectors.frontTop.y + c.cuboidVectors.frontLeft.y },
        { x: c.x + c.cuboidVectors.depthVec.x, y: c.y + c.cuboidVectors.depthVec.y },
      ]
      const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
      bx = Math.min(...xs) - 8; by = Math.min(...ys) - 8
      bw = Math.max(...xs) - Math.min(...xs) + 16; bh = Math.max(...ys) - Math.min(...ys) + 16
    }
    const old = oldMap.get(c.type + '_comp_' + i)
    const cx = c.cuboidVectors ? (bx + bw / 2) : c.x
    const cy = c.cuboidVectors ? (by + bh / 2) : c.y
    next.push({
      id: old?.id ?? nextObjectId(),
      kind: 'component',
      selected: old?.selected ?? false,
      bbox: { x: bx, y: by, w: bw, h: bh },
      pose: old?.pose ?? { x: Math.round(cx), y: Math.round(cy), z: 0, a: 0, b: 0, c: 0 },
      componentIndex: i,
    })
  }

  // 笔划 → 对象
  for (let i = 0; i < strokeHistory.length; i++) {
    const s = strokeHistory[i]
    if (!s.points.length) continue
    const old = oldMap.get('stroke_' + i)
    const bb = strokeBBox(s.points, s.width)
    next.push({
      id: old?.id ?? nextObjectId(),
      kind: 'stroke',
      selected: old?.selected ?? false,
      bbox: bb,
      pose: old?.pose ?? { x: Math.round(bb.x + bb.w / 2), y: Math.round(bb.y + bb.h / 2), z: 0, a: 0, b: 0, c: 0 },
      strokeIndex: i,
      groupId: s.groupId,
    })
  }

  objects.splice(0, objects.length, ...next)
  // 同步 selectedIds：只保留 objects 中标记为 selected 的 id
  selectedIds.value = next.filter(o => o.selected).map(o => o.id)

  // 便签组：把带 groupId 的笔划按组聚合（一组 = 一个可整体操作的对象）
  noteGroups.clear()
  const noteAcc = new Map<string, { indices: number[]; minX: number; minY: number; maxX: number; maxY: number }>()
  for (let i = 0; i < strokeHistory.length; i++) {
    const s = strokeHistory[i]
    if (!s.groupId) continue
    let a = noteAcc.get(s.groupId)
    if (!a) { a = { indices: [], minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }; noteAcc.set(s.groupId, a) }
    a.indices.push(i)
    const bb = strokeBBox(s.points, s.width)
    a.minX = Math.min(a.minX, bb.x); a.minY = Math.min(a.minY, bb.y)
    a.maxX = Math.max(a.maxX, bb.x + bb.w); a.maxY = Math.max(a.maxY, bb.y + bb.h)
  }
  for (const [gid, a] of noteAcc) {
    noteGroups.set(gid, { bbox: { x: a.minX, y: a.minY, w: a.maxX - a.minX, h: a.maxY - a.minY }, strokeIndices: a.indices })
  }
}

/** 坐标处的对象（从上到下） */
function objectAt(x: number, y: number): DesignObject | null {
  for (let i = objects.length - 1; i >= 0; i--) {
    const o = objects[i]
    if (x >= o.bbox.x && x <= o.bbox.x + o.bbox.w && y >= o.bbox.y && y <= o.bbox.y + o.bbox.h) return o
  }
  return null
}

// === 工具切换统一入口 ===
// placing/threeDPlacing 会无条件拦截指针事件（onPointerDown 最前分支），
// 任何工具切换都必须先退出放置状态，否则会卡在立体几何放置里切不回画笔（绘画/书写/选择全部失效）。
function exitPlacing() {
  if (placing.value) placing.value = null
  placeAnchor.value = null
  if (threeDPlacing.value) cancel3DPlacing()
}
function switchTool(mode: 'pen' | 'eraser' | 'select' | 'shape' | 'pan') {
  exitPlacing()
  toolMode.value = mode
}
function switchPen() {
  exitPlacing()
  if (writingMode.value) toggleWriting()  // 书写中切绘画 = 完成当前便签
  toolMode.value = 'pen'
}

// === 书写模式 / 便签组 ===

function toggleWriting() {
  if (writingMode.value) {
    // 完成书写：有内容则选中刚完成的便签，无内容则丢弃
    const gid = currentGroupId.value
    currentGroupId.value = null
    writingMode.value = false
    if (gid && noteGroups.has(gid) && noteGroups.get(gid)!.strokeIndices.length > 0) {
      selectNote(gid)
      scheduleAutoSave()
    }
    return
  }
  writingMode.value = true
  exitPlacing()  // 书写即落笔：先退出组件/立体几何放置状态，否则指针事件仍被放置逻辑拦截
  currentGroupId.value = nextObjectId()
  toolMode.value = 'pen'
}

/** 坐标处的便签组 id（含背景外扩区域，后建的便签优先命中） */
function noteAt(x: number, y: number): string | null {
  for (const gid of [...noteGroups.keys()].reverse()) {
    const b = noteGroups.get(gid)!.bbox
    if (x >= b.x - NOTE_PAD && x <= b.x + b.w + NOTE_PAD && y >= b.y - NOTE_PAD && y <= b.y + b.h + NOTE_PAD) return gid
  }
  return null
}

/** 选中便签：其成员笔划整体高亮，四角出现缩放柄 */
function selectNote(gid: string) {
  for (const o of objects) o.selected = o.groupId === gid
  selectedIds.value = objects.filter(o => o.groupId === gid).map(o => o.id)
  selectedNoteId.value = gid
  if (sctx) redrawStrokes()
  if (dctx) redrawAllDesign()
}

function clearNoteSelection() {
  selectedNoteId.value = null
  for (const o of objects) o.selected = false
  selectedIds.value = []
}

/** 命中选中便签的四角缩放柄（柄画在外扩角上，与 drawNoteHighlight 一致） */
function noteHandleAt(x: number, y: number): 'tl' | 'tr' | 'bl' | 'br' | null {
  if (!selectedNoteId.value) return null
  const b = noteGroups.get(selectedNoteId.value)?.bbox
  if (!b) return null
  const H = 9
  const x0 = b.x - NOTE_PAD, y0 = b.y - NOTE_PAD
  const x1 = b.x + b.w + NOTE_PAD, y1 = b.y + b.h + NOTE_PAD
  const corners: [string, number, number][] = [
    ['tl', x0, y0], ['tr', x1, y0], ['bl', x0, y1], ['br', x1, y1],
  ]
  for (const [k, cx, cy] of corners) {
    if (Math.abs(x - cx) <= H && Math.abs(y - cy) <= H) return k as any
  }
  return null
}

/** 以 (cx,cy) 为中心对便签全部笔划等比缩放 s 倍 */
function applyNoteScale(gid: string, cx: number, cy: number, s: number) {
  const g = noteGroups.get(gid)
  if (!g) return
  for (const idx of g.strokeIndices) {
    const st = strokeHistory[idx]
    if (!st) continue
    for (const p of st.points) {
      p.x = cx + (p.x - cx) * s
      p.y = cy + (p.y - cy) * s
    }
    st.width = Math.max(0.2, st.width * s)
  }
  buildObjects()
  redrawStrokes()
}

/** 删除选中的便签（仅移除其笔划数据，画布全量重绘） */
function deleteSelectedNote() {
  const gid = selectedNoteId.value
  if (!gid) return
  const layer = layers.find(l => l.id === activeLayerId)
  if (layer) {
    layer.strokes = layer.strokes.filter(s => s.groupId !== gid)
    strokeHistory = layer.strokes
  }
  clearNoteSelection()
  buildObjects()
  redrawStrokes()
  checkInk()
  scheduleAutoSave()
}

/** 移动选中的对象 */
function moveSelected(dx: number, dy: number) {
  for (const id of selectedIds.value) {
    const o = objects.find(ob => ob.id === id)
    if (!o) continue
    o.bbox.x += dx; o.bbox.y += dy
    o.pose.x += dx; o.pose.y += dy
    // 同步到源数据
    if (o.componentIndex != null) {
      const c = components.value[o.componentIndex]
      if (c) { c.x = o.bbox.x + o.bbox.w / 2; c.y = o.bbox.y + o.bbox.h / 2 }
    }
    if (o.strokeIndex != null) {
      const s = strokeHistory[o.strokeIndex]
      if (s) {
        for (const pt of s.points) { pt.x += dx; pt.y += dy }
      }
    }
  }
  if (selectedIds.value.length > 0) {
    if (dctx && sctx) {
      dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H)
      drawOrigin()
      for (const c of components.value) {
        if (c.cuboidVectors) drawCuboidFromVectors(dctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec)
        else if (c.cylinderRadius) drawCylinder2D(dctx, c.x, c.y, c.cylinderRadius, c.size || 50)
        else if (c.coneRadius && c.coneTip) {
          if (c.type === 'rcone') drawRightCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y)
          else drawCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip)
        } else if (c.type === 'text') drawComponent(dctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor)
        else drawComponent(dctx, c.type, c.x, c.y, c.size)
      }
      redrawStrokes()
    }
  }
}

/** 根据 pose 更新对象的画布位置 */
function applyPoseToObject(o: DesignObject) {
  const dx = o.pose.x - (o.bbox.x + o.bbox.w / 2)
  const dy = o.pose.y - (o.bbox.y + o.bbox.h / 2)
  if (dx === 0 && dy === 0) return
  o.bbox.x += dx; o.bbox.y += dy
  if (o.componentIndex != null) {
    const c = components.value[o.componentIndex]
    if (c) { c.x = o.pose.x; c.y = o.pose.y }
  }
  if (o.strokeIndex != null) {
    const s = strokeHistory[o.strokeIndex]
    if (s) { for (const pt of s.points) { pt.x += dx; pt.y += dy } }
  }
}

/** 当前选中对象的位姿信息（用于编辑面板绑定） */
const editingPose = computed(() => {
  const sel = objects.filter(o => o.selected)
  if (sel.length === 0) return null
  if (sel.length === 1) return sel[0].pose
  // 多选：取平均
  const pose = { x: 0, y: 0, z: 0, a: 0, b: 0, c: 0 }
  for (const o of sel) {
    pose.x += o.pose.x; pose.y += o.pose.y; pose.z += o.pose.z
    pose.a += o.pose.a; pose.b += o.pose.b; pose.c += o.pose.c
  }
  const n = sel.length
  pose.x = Math.round(pose.x / n); pose.y = Math.round(pose.y / n)
  pose.z = Math.round(pose.z / n); pose.a = Math.round(pose.a / n)
  pose.b = Math.round(pose.b / n); pose.c = Math.round(pose.c / n)
  return pose
})

function onPoseInput(axis: string, val: number) {
  for (const id of selectedIds.value) {
    const o = objects.find(ob => ob.id === id)
    if (!o) continue
    (o.pose as any)[axis] = val
    if (axis === 'x' || axis === 'y') applyPoseToObject(o)
  }
  if (dctx) redrawAllDesign()
  scheduleAutoSave()
}

/** 绘制选中高亮 */
function drawSelectionHighlights(dc: CanvasRenderingContext2D) {
  for (const o of objects) {
    if (!o.selected) continue
    if (o.groupId) continue  // 便签成员：由便签整体高亮统一表示
    dc.save()
    dc.strokeStyle = '#4a7dff'
    dc.lineWidth = 2
    dc.setLineDash([5, 3])
    dc.strokeRect(o.bbox.x, o.bbox.y, o.bbox.w, o.bbox.h)
    // 手柄方块
    dc.fillStyle = '#4a7dff'
    const h = 7
    const { x, y, w, h: bh } = o.bbox
    for (const [cx, cy] of [[x, y], [x + w, y], [x, y + bh], [x + w, y + bh]] as [number,number][]) {
      dc.fillRect(cx - h/2, cy - h/2, h, h)
    }
    dc.restore()
  }
}

/** 重绘全部设计层内容（组件 + 原点 + 选中高亮） */
function redrawAllDesign() {
  if (!dctx) return
  dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H)
  drawOrigin()
  for (const c of components.value) {
    if (c.cuboidVectors) drawCuboidFromVectors(dctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec)
    else if (c.cylinderRadius) drawCylinder2D(dctx, c.x, c.y, c.cylinderRadius, c.size || 50)
    else if (c.coneRadius && c.coneTip) {
      if (c.type === 'rcone') drawRightCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y)
      else drawCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip)
    } else if (c.type === 'text') drawComponent(dctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor)
    else drawComponent(dctx, c.type, c.x, c.y, c.size)
  }
  drawSelectionHighlights(dctx)
}

// AI 解读（双模式：结构 / 图像）
const interpreting = ref(false)
const interpCollapsed = ref(false)
const interpMessages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
let lastInterpText = '' // 保持兼容，初始解读结果
const interpText = computed(() => {
  const first = interpMessages.value.find(m => m.role === 'assistant')
  return first?.content || ''
})
const followupInput = ref('')
const followupStreaming = ref(false)
const streamingContent = ref('')
const interpWidth = ref(360)
let interpResizing = false
let resizeStartX = 0
let resizeStartW = 0
const interpMode = ref<'structure' | 'vision'>('structure')
const interpBodyEl = ref<HTMLDivElement | null>(null)
let interpAbort: AbortController | null = null

function renderMarkdown(text: string): string {
  if (!text) return ''
  let s = text
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/\n## (.+)/g, '\n<h4>$1</h4>')
  s = s.replace(/\n### (.+)/g, '\n<h3>$1</h3>')
  s = s.replace(/\n- (.+)/g, '\n<li>$1</li>')
  s = s.replace(/\n(\d+)\. (.+)/g, '\n<li>$1. $2</li>')
  s = s.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
  s = s.replace(/\n\n/g, '<br/><br/>')
  s = s.replace(/\n/g, '<br/>')
  return s
}

async function switchInterpretMode(mode: 'structure' | 'vision') {
  if (interpreting.value || followupStreaming.value) return
  interpMode.value = mode
  interpMessages.value = []
  streamingContent.value = ''
  await doInterpret(mode)
}

async function doInterpret(mode: 'structure' | 'vision', followup?: string, history?: { role: string; content: string }[]) {
  if (interpreting.value && !followup) return
  if (followup) {
    followupStreaming.value = true
    streamingContent.value = ''
    interpMessages.value.push({ role: 'user', content: followup })
  } else if (history && history.length > 0) {
    // 空追问重新解读：保留对话历史
    followupStreaming.value = true
    streamingContent.value = ''
  } else {
    interpreting.value = true
    interpMessages.value = []
    streamingContent.value = ''
  }
  const llmConfig = JSON.stringify({
    inference: { ...llmSettings.inference },
    vision: { ...llmSettings.vision },
  })

  interpAbort = new AbortController()
  try {
    const fd = new FormData()
    fd.append('llm_config', llmConfig)
    fd.append('mode', mode)
    if (followup) {
      fd.append('followup', followup)
      fd.append('history', JSON.stringify(history || []))
    }

    if (mode === 'vision') {
      // 计算内容包围盒（笔迹 + 组件），裁剪截图
      const MARGIN = 80
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      
      // 组件包围盒
      for (const c of components.value) {
        if (c.cuboidVectors) {
          const pts = [
            { x: c.x, y: c.y },
            { x: c.x + c.cuboidVectors.frontTop.x, y: c.y + c.cuboidVectors.frontTop.y },
            { x: c.x + c.cuboidVectors.frontLeft.x, y: c.y + c.cuboidVectors.frontLeft.y },
            { x: c.x + c.cuboidVectors.frontTop.x + c.cuboidVectors.frontLeft.x, y: c.y + c.cuboidVectors.frontTop.y + c.cuboidVectors.frontLeft.y },
            { x: c.x + c.cuboidVectors.depthVec.x, y: c.y + c.cuboidVectors.depthVec.y },
          ]
          for (const p of pts) { minX = Math.min(minX, p.x); minY = Math.min(minY, p.y); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y) }
        } else if (c.coneRadius && c.coneTip) {
          const r = c.coneRadius
          minX = Math.min(minX, c.x - r, c.coneTip.x); minY = Math.min(minY, c.y - r, c.coneTip.y)
          maxX = Math.max(maxX, c.x + r, c.coneTip.x); maxY = Math.max(maxY, c.y + r, c.coneTip.y)
        } else if (c.cylinderRadius) {
          const r = c.cylinderRadius, h = c.size || 50
          minX = Math.min(minX, c.x - r); minY = Math.min(minY, c.y - r)
          maxX = Math.max(maxX, c.x + r); maxY = Math.max(maxY, c.y + h)
        } else {
          const s = (c.size || 44) / 2
          minX = Math.min(minX, c.x - s); minY = Math.min(minY, c.y - s)
          maxX = Math.max(maxX, c.x + s); maxY = Math.max(maxY, c.y + s)
        }
      }
      // 笔迹包围盒（只扫可见图层）
      for (const layer of layers) {
        if (!layer.visible) continue
        for (const st of layer.strokes) {
          for (const pt of st.points) {
            minX = Math.min(minX, pt.x); minY = Math.min(minY, pt.y)
            maxX = Math.max(maxX, pt.x); maxY = Math.max(maxY, pt.y)
          }
        }
      }
      
      if (!isFinite(minX)) {
        // 没有内容，用默认区域
        minX = W/2 - 200; minY = H/2 - 200; maxX = W/2 + 200; maxY = H/2 + 200
      }
      minX = Math.max(0, minX - MARGIN)
      minY = Math.max(0, minY - MARGIN)
      maxX = Math.min(W, maxX + MARGIN)
      maxY = Math.min(H, maxY + MARGIN)
      const cropW = Math.max(200, maxX - minX)
      const cropH = Math.max(200, maxY - minY)
      
      // 渲染画布截图：只包含用户内容，不含坐标网格/轴线
      const merged = document.createElement('canvas')
      merged.width = cropW
      merged.height = cropH
      const mctx = merged.getContext('2d')!
      mctx.fillStyle = '#ffffff'
      mctx.fillRect(0, 0, cropW, cropH)
      mctx.save()
      mctx.translate(-minX, -minY)
      // 绘制所有已放置的立体组件（不含网格和坐标轴）
      for (const c of components.value) {
        if (c.cuboidVectors) {
          drawCuboidFromVectors(mctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec)
        } else if (c.cylinderRadius) {
          drawCylinder2D(mctx, c.x, c.y, c.cylinderRadius, c.size || 50)
        } else if (c.coneRadius && c.coneTip) {
          if (c.type === 'rcone') drawRightCone2D(mctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y)
          else drawCone2D(mctx, c.x, c.y, c.coneRadius, c.coneTip)
        } else if (c.type === 'text') {
          drawComponent(mctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor)
        } else {
          drawComponent(mctx, c.type, c.x, c.y, c.size)
        }
      }
      // 叠加手绘笔迹层（DPR 缩放适配）
      if (sketchCanvas.value) mctx.drawImage(sketchCanvas.value, minX * DPR, minY * DPR, cropW * DPR, cropH * DPR, 0, 0, cropW, cropH)
      mctx.restore()
      
      const blob = await new Promise<Blob>(resolve => merged.toBlob(b => resolve(b!), 'image/png'))
      fd.append('file', blob, 'sketch.png')
      // 始终附带结构化场景数据（位置/尺寸/角度）
      fd.append('scene', buildSceneDescription())
    } else if (mode === 'structure' && !followup) {
      fd.append('scene', buildSceneDescription())
    }

    const resp = await apiRaw('/api/interpret', {
      method: 'POST',
      body: fd,
      signal: interpAbort.signal,
    })
    if (!resp.ok || !resp.body) {
      const detail = await resp.text().catch(() => '')
      const msg = resp.status === 401 ? '登录已过期,请重新登录'
        : resp.status === 403 ? '未配置模型:请先在「设置 → 模型配置」中配置后再使用 AI 解读'
        : `解读失败(HTTP ${resp.status})${detail ? ': ' + detail.slice(0, 200) : ''}`
      interpMessages.value.push({ role: 'assistant', content: '❌ ' + msg })
      interpreting.value = false
      followupStreaming.value = false
      return
    }
    const reader = resp.body?.getReader()
    if (!reader) { interpreting.value = false; followupStreaming.value = false; return }

    // 在对话列表中插入空 AI 消息，流式填入
    const targetIdx = interpMessages.value.length
    interpMessages.value.push({ role: 'assistant', content: '' })

    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'token') {
            interpMessages.value[targetIdx].content += data.content
            streamingContent.value = interpMessages.value[targetIdx].content
            nextTick(() => {
              if (interpBodyEl.value) interpBodyEl.value.scrollTop = interpBodyEl.value.scrollHeight
            })
          } else if (data.type === 'error') {
            const tip = data.code === 'MODEL_NOT_CONFIGURED' ? `\n\n⚙️ ${data.content}\n（左侧栏「设置 → 模型配置」填入 API Key 保存后重试）` : `\n\n❌ ${data.content}`
            interpMessages.value[targetIdx].content += tip
          }
        }
      }
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      const msg = `❌ 解读失败: ${e.message || e}`
      if (interpMessages.value.length > 0 && interpMessages.value[interpMessages.value.length - 1].role === 'assistant') {
        interpMessages.value[interpMessages.value.length - 1].content += '\n\n' + msg
      } else {
        interpMessages.value.push({ role: 'assistant', content: msg })
      }
    }
  } finally {
    interpreting.value = false
    followupStreaming.value = false
    streamingContent.value = ''
    interpAbort = null
    scheduleAutoSave()
  }
}

async function sendOrStartInterpret() {
  if (interpreting.value || followupStreaming.value) return
  const text = followupInput.value.trim()
  followupInput.value = ''
  if (interpMessages.value.length === 0) {
    // 首次：解读画布（空输入用默认 prompt，有输入用用户问题）
    interpMode.value = 'vision'
    await doInterpret('vision', text || undefined)
  } else {
    // 追问
    const history = interpMessages.value.map(m => ({ role: m.role, content: m.content }))
    if (text) {
      await doInterpret(interpMode.value, text, history)
    } else {
      // 空输入追问 → 重新解读画布
      interpMode.value = 'vision'
      await doInterpret('vision', undefined, history)
    }
  }
}

function onResizePointerDown(e: PointerEvent) {
  interpResizing = true
  resizeStartX = e.clientX
  resizeStartW = interpWidth.value
  try { (e.target as HTMLElement).setPointerCapture(e.pointerId) } catch {}
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
}
function onResizePointerMove(e: PointerEvent) {
  if (!interpResizing) return
  const dx = resizeStartX - e.clientX
  interpWidth.value = Math.max(220, Math.min(600, resizeStartW + dx))
}
function onResizePointerUp() {
  interpResizing = false
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
}

function stopInterpret() {
  if (interpAbort) { interpAbort.abort(); interpAbort = null }
  interpMessages.value = []
  streamingContent.value = ''
  followupInput.value = ''
  interpreting.value = false
  followupStreaming.value = false
}

let threeDStart: { x: number; y: number } | null = null
let threeDDragging = false
// cuboid 三笔绘制状态
const cuboidPhase = ref(0)           // 0=未激活, 1=横划, 2=竖划, 3=斜划
// cylinder 两笔绘制状态
const cylinderPhase = ref(0)         // 0=未激活, 1=定直径, 2=定高度
const cylinderAnchor = ref<{x:number;y:number}|null>(null)
const cylinderRadius = ref(0)
// cone 两笔绘制状态
const conePhase = ref(0)             // 0=未激活, 1=定底面, 2=定顶点
const coneAnchor = ref<{x:number;y:number}|null>(null)
const coneRadius = ref(0)
let cuboidAnchor: {x:number;y:number} | null = null
let cuboidFrontTop: {x:number;y:number} | null = null    // 横划终点(相对锚点)
let cuboidFrontLeft: {x:number;y:number} | null = null   // 竖划终点(相对锚点)
let cuboidPreviewSnap: ImageData | null = null

// cuboid 辅助线：在表达层画实线
function cuboidDrawSolidEdge(v1: {x:number;y:number}, v2: {x:number;y:number}) {
  if (!sctx) return
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.setLineDash([])
  sctx.beginPath()
  sctx.moveTo(v1.x, v1.y)
  sctx.lineTo(v2.x, v2.y)
  sctx.stroke()
  sctx.restore()
}
function cuboidDrawSolidRect(anc: {x:number;y:number}, ft: {x:number;y:number}, fl: {x:number;y:number}) {
  if (!sctx) return
  const B = { x: anc.x + ft.x, y: anc.y + ft.y }
  const D = { x: anc.x + fl.x, y: anc.y + fl.y }
  const C = { x: anc.x + ft.x + fl.x, y: anc.y + ft.y + fl.y }
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.setLineDash([])
  sctx.beginPath()
  sctx.moveTo(anc.x, anc.y); sctx.lineTo(B.x, B.y)
  sctx.lineTo(C.x, C.y); sctx.lineTo(D.x, D.y)
  sctx.closePath()
  sctx.stroke()
  sctx.fillStyle = '#4a7dff'
  sctx.beginPath(); sctx.arc(anc.x, anc.y, 4, 0, Math.PI*2)
  sctx.fill()
  sctx.restore()
}

const selecting = ref(false)
const selectMode = ref<'rect' | 'lasso'>('rect')

function toggleSelect() {
  if (toolMode.value !== 'select') { exitPlacing(); toolMode.value = 'select'; selectMode.value = 'rect'; return }
  if (selectMode.value === 'rect') { selectMode.value = 'lasso'; return }
  exitPlacing()
  toolMode.value = 'pen'; selectMode.value = 'rect'
}

// === 形状工具 ===
const shapeType = ref<'rect' | 'ellipse' | 'polygon' | 'lasso'>('rect')
// 形状绘制状态
let shapeStart: { x: number; y: number } | null = null
let shapePoints: { x: number; y: number }[] = []  // 多边形顶点/套索轨迹
let shapeDrawn = false  // 形状是否已画出（用于撤销）

// === 橡皮擦 ===
let erasing = false
let eraserPoints: { x: number; y: number }[] = []
const ERASER_SIZE = 18  // 橡皮直径（px）

function applyEraserDot(raw: { x: number; y: number }) {
  if (!sctx) return
  sctx.save()
  sctx.globalCompositeOperation = 'destination-out'
  sctx.beginPath()
  sctx.arc(raw.x, raw.y, ERASER_SIZE / 2, 0, Math.PI * 2)
  sctx.fill()
  sctx.restore()
}

function applyEraserStroke(raw: { x: number; y: number }) {
  if (!sctx) return
  sctx.save()
  sctx.globalCompositeOperation = 'destination-out'
  sctx.lineWidth = ERASER_SIZE
  sctx.lineCap = 'round'
  sctx.beginPath()
  sctx.moveTo(lastX, lastY)
  sctx.lineTo(raw.x, raw.y)
  sctx.stroke()
  sctx.restore()
  lastX = raw.x
  lastY = raw.y
  eraserPoints.push({ x: raw.x, y: raw.y })
  hasInk.value = checkHasInk()
}

function setShape(t: 'rect' | 'ellipse' | 'polygon' | 'lasso') {
  exitPlacing()
  shapeType.value = t
  toolMode.value = 'shape'
  shapePoints = []
  shapeStart = null
}

// 形状绘制：按下开始，拖动预览，抬起完成（多边形点击加点，双击/回车结束）
function shapePointerDown(raw: { x: number; y: number }) {
  shapeDrawn = false
  if (shapeType.value === 'polygon') {
    // 多边形：点击加顶点，接近起点时闭合
    shapePoints.push({ x: raw.x, y: raw.y })
    if (shapePoints.length === 1) shapeStart = { x: raw.x, y: raw.y }
    // 预览当前折线
    drawShapePreview()
    // 点击回起点附近 → 闭合完成
    if (shapePoints.length > 2 && shapeStart && Math.hypot(raw.x - shapeStart.x, raw.y - shapeStart.y) < 20) {
      finishShape()
    }
    return
  }
  // rect/ellipse/lasso：按下记录起点（拖拽式；工具保持选中，可连续画）
  shapeStart = { x: raw.x, y: raw.y }
  shapePoints = [{ x: raw.x, y: raw.y }]
  lastX = raw.x; lastY = raw.y
}

function shapePointerMove(raw: { x: number; y: number }) {
  if (!shapeStart) return
  if (shapeType.value === 'polygon') {
    // 多边形预览：最后一段连向鼠标
    if (shapePoints.length) drawShapePreview(raw)
    return
  }
  if (shapeType.value === 'lasso') {
    // 自由圈选：累积轨迹点
    shapePoints.push({ x: raw.x, y: raw.y })
    drawShapePreview(raw)
    return
  }
  // rect/ellipse：拖拽预览（记录结束点）
  shapePoints = [{ x: shapeStart.x, y: shapeStart.y }, { x: raw.x, y: raw.y }]
  lastX = raw.x; lastY = raw.y
  drawShapePreview(raw)
}

function shapePointerUp(raw: { x: number; y: number }) {
  if (!shapeStart) return
  if (shapeType.value === 'polygon') {
    // 多边形在 pointerDown 处理，up 不结束
    return
  }
  if (shapeType.value === 'lasso') {
    // 自由圈选：自动封闭（首尾相连）
    if (shapePoints.length > 4) {
      drawShapePreview(raw, true)
      finishShape()
    }
    shapePoints = []
    shapeStart = null
    return
  }
  // rect/ellipse：释放画圆/画矩形（拖动中 ESC 可取消）
  // 最小尺寸阈值：无拖动的单击不落账（防零尺寸退化块，2026-09-02）
  const __dx = Math.abs(lastX - shapeStart.x), __dy = Math.abs(lastY - shapeStart.y)
  if (__dx < 3 && __dy < 3) { shapeStart = null; shapePoints = []; return }
  finishShape()
  shapeStart = null
}

// 画形状预览（临时，不写入撤销栈）
// rect/ellipse 用快照方式避免残留；polygon/lasso 只画增量
let shapeSnapshot: ImageData | null = null

function drawShapePreview(cursor?: { x: number; y: number }, closing = false) {
  if (!pctx || !shapeStart) return
  // 预览层绘制：每次 clearRect 后重画（2026-09-02 修复滞后/重线——弃整画布快照搬运）
  pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
  const b = currentBrush.value
  pctx.save()
  pctx.globalAlpha = b.alpha * 0.7
  pctx.strokeStyle = penColor.value
  pctx.lineWidth = brushWidth(0.5)
  pctx.lineCap = 'round'
  pctx.lineJoin = 'round'
  pctx.beginPath()
  if (shapeType.value === 'rect') {
    const w = (cursor?.x ?? shapeStart.x) - shapeStart.x
    const h = (cursor?.y ?? shapeStart.y) - shapeStart.y
    pctx.rect(shapeStart.x, shapeStart.y, w, h)
  } else if (shapeType.value === 'ellipse') {
    const w = (cursor?.x ?? shapeStart.x) - shapeStart.x
    const h = (cursor?.y ?? shapeStart.y) - shapeStart.y
    pctx.ellipse(shapeStart.x + w / 2, shapeStart.y + h / 2, Math.abs(w / 2), Math.abs(h / 2), 0, 0, Math.PI * 2)
    // 拖拽中辅助线：圆心→光标 半径线
    pctx.moveTo(shapeStart.x, shapeStart.y)
    pctx.lineTo(cursor?.x ?? shapeStart.x, cursor?.y ?? shapeStart.y)
  } else if (shapeType.value === 'polygon') {
    const pts = shapePoints
    pctx.moveTo(pts[0]?.x ?? 0, pts[0]?.y ?? 0)
    for (let i = 1; i < pts.length; i++) pctx.lineTo(pts[i].x, pts[i].y)
    if (cursor) pctx.lineTo(cursor.x, cursor.y)
  } else if (shapeType.value === 'lasso') {
    // 自由圈选：只画已累积的轨迹（每次从快照重画全部）
    const pts = closing ? [...shapePoints, shapePoints[0]] : shapePoints
    pctx.moveTo(pts[0]?.x ?? 0, pts[0]?.y ?? 0)
    for (let i = 1; i < pts.length; i++) pctx.lineTo(pts[i].x, pts[i].y)
  }
  pctx.stroke()
  pctx.restore()
}

// 完成形状：正式绘制到画布（写入撤销栈）
function finishShape() {
  if (!sctx || !shapeStart) return
  if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)  // 清预览层，防预览+正式线重影
  const b = currentBrush.value
  sctx.save()
  sctx.globalAlpha = b.alpha
  sctx.strokeStyle = penColor.value
  sctx.lineWidth = brushWidth(0.5)
  sctx.lineCap = 'round'
  sctx.lineJoin = 'round'
  sctx.beginPath()
  if (shapeType.value === 'rect') {
    const w = (shapePoints[shapePoints.length - 1]?.x ?? shapeStart.x) - shapeStart.x
    const h = (shapePoints[shapePoints.length - 1]?.y ?? shapeStart.y) - shapeStart.y
    sctx.rect(shapeStart.x, shapeStart.y, w, h)
  } else if (shapeType.value === 'ellipse') {
    const last = shapePoints[shapePoints.length - 1] ?? shapeStart
    const w = last.x - shapeStart.x
    const h = last.y - shapeStart.y
    sctx.ellipse(shapeStart.x + w / 2, shapeStart.y + h / 2, Math.abs(w / 2), Math.abs(h / 2), 0, 0, Math.PI * 2)
  } else if (shapeType.value === 'polygon') {
    sctx.moveTo(shapePoints[0].x, shapePoints[0].y)
    for (let i = 1; i < shapePoints.length; i++) sctx.lineTo(shapePoints[i].x, shapePoints[i].y)
    sctx.closePath()  // 自动封闭
  } else if (shapeType.value === 'lasso') {
    sctx.moveTo(shapePoints[0].x, shapePoints[0].y)
    for (let i = 1; i < shapePoints.length; i++) sctx.lineTo(shapePoints[i].x, shapePoints[i].y)
    sctx.closePath()  // 自动封闭
  }
  sctx.stroke()
  sctx.restore()
  // 记录到撤销栈
  strokeHistory.push({ color: penColor.value, width: brushWidth(0.5), points: [...shapePoints] })
  shapeDrawn = true
  hasInk.value = true
  shapePoints = []
  shapeStart = null
  shapeSnapshot = null
}

// 组件库（三类）
interface ShapeDef { type: string; name: string; icon: string; category: string }
const ALL_SHAPES: ShapeDef[] = [
  { type: 'gear', name: '齿轮', icon: '⚙️', category: 'mechanical' },
  { type: 'hinge', name: '铰链', icon: '🔩', category: 'mechanical' },
  { type: 'actuator', name: '电动推杆', icon: '🔧', category: 'mechanical' },
  { type: 'motor', name: '电机', icon: '🌀', category: 'mechanical' },
  { type: 'bearing', name: '轴承', icon: '⭕', category: 'mechanical' },
  { type: 'screw', name: '丝杠', icon: '📐', category: 'mechanical' },
  { type: 'slider', name: '滑轨', icon: '🛤️', category: 'mechanical' },
  { type: 'wheel', name: '滚轮', icon: '🛞', category: 'mechanical' },
  { type: 'circle', name: '圆', icon: '○', category: '2d' },
  { type: 'square', name: '矩形', icon: '□', category: '2d' },
  { type: 'triangle', name: '三角形', icon: '△', category: '2d' },
  { type: 'diamond', name: '菱形', icon: '◇', category: '2d' },
  { type: 'pentagon', name: '五边形', icon: '⬠', category: '2d' },
  { type: 'hexagon', name: '六边形', icon: '⬡', category: '2d' },
  { type: 'line', name: '直线', icon: '╱', category: '2d' },
  { type: 'arrow', name: '箭头', icon: '→', category: '2d' },
  { type: 'cube', name: '立方体', icon: '🟦', category: '3d' },
  { type: 'cuboid', name: '长方体', icon: '🟫', category: '3d' },
  { type: 'sphere', name: '球体', icon: '🔵', category: '3d' },
  { type: 'cylinder', name: '圆柱', icon: '🫙', category: '3d' },
  { type: 'cone', name: '圆锥', icon: '🔺', category: '3d' },
  { type: 'rcone', name: '正圆锥', icon: '📐', category: '3d' },
  { type: 'pyramid', name: '棱锥', icon: '🔻', category: '3d' },
  { type: 'text', name: '文字', icon: 'T', category: '3d' },
]
const currentShapes = computed(() => ALL_SHAPES.filter(s => s.category === compCategory.value))
const compCategoryLabel = computed(() => {
  const m: Record<string,string> = { mechanical: '🔧 机械组件', '2d': '📐 平面几何', '3d': '📦 立体几何' }
  return m[compCategory.value] || ''
})
const compName = (t: string) => ALL_SHAPES.find(c => c.type === t)?.name || t
const compIcon = (t: string) => ALL_SHAPES.find(c => c.type === t)?.icon || '🔩'
const components = ref<{ type: string; x: number; y: number; size?: number; cylinderRadius?: number; coneRadius?: number; coneTip?: {x:number;y:number}; cuboidVectors?: { frontTop: {x:number;y:number}; frontLeft: {x:number;y:number}; depthVec: {x:number;y:number} }; text?: string; textFont?: string; textColor?: string }[]>([])

// 画布尺寸
let W = 800, H = 500
const DPR = window.devicePixelRatio || 1
// 缩放（设计层）
const zoom = ref(1)
const ZOOM_MIN = 0.3, ZOOM_MAX = 4
const WORKSPACE_W = 6000, WORKSPACE_H = 4000
// 画布平移（移动画布工具，初始值在 resizeCanvas 中按视口居中）
const panX = ref(-1), panY = ref(-1)
const panning = ref(false)
let panStart = { x: 0, y: 0 }
let panOrigin = { x: 0, y: 0 }

// 比例尺标签：基于 100px 线长，换算实际长度（默认 1px=1mm）
const scaleBarLabel = computed(() => {
  const mm = 100 / zoom.value
  if (mm >= 1000) return `${(mm/1000).toFixed(1)}m`
  if (mm >= 10) return `${Math.round(mm)}mm`
  if (mm >= 1) return `${mm.toFixed(1)}mm`
  return `${(mm*1000).toFixed(0)}μm`
})
// 框选 / 自由圈选
const selRect = ref<{ x: number; y: number; w: number; h: number } | null>(null)
let selStart: { x: number; y: number } | null = null
const selRectStyle = computed(() => selRect.value ? {
  left: selRect.value.x + 'px',
  top: selRect.value.y + 'px',
  width: selRect.value.w + 'px',
  height: selRect.value.h + 'px',
} : {})
// 自由圈选状态
let lassoPoints: { x: number; y: number }[] = []
let lassoSnapshot: ImageData | null = null

let dctx: CanvasRenderingContext2D | null = null  // 设计层 ctx
let sctx: CanvasRenderingContext2D | null = null  // 表达层 ctx
let pctx: CanvasRenderingContext2D | null = null  // 预览层 ctx
let drawing = false
// 笔画优先的轻点判定：画笔模式下笔尖落在对象/便签上仍先落笔；
// 抬笔时若位移<6px 判定为轻点→转换为选中（丢弃笔迹）；真实笔画照常保留
let penTapPending: { kind: 'obj' | 'note'; id: number | string } | null = null
let penTapStart = { x: 0, y: 0 }
let lastX = 0, lastY = 0, lastPressure = 0
// SketchDocument — 多文档标签页管理
const docs = reactive<SketchDocument[]>([createDocument('3d')])
const docIndex = ref(0)
const doc = computed(() => docs[docIndex.value])
let _docCounter = 1

// 本地 Layer 类型（兼容 SketchLayer 但 locked 可选，方便模板）
interface Layer { id: number; name: string; visible: boolean; locked?: boolean; strokes: StrokeDataType[] }

// layers / activeLayerId / strokeHistory 始终指向当前 doc 中对应字段
let layers: SketchLayer[] = []
let activeLayerId = 0
let nextLayerId = 1
let strokeHistory: StrokeDataType[] = []

function rebindDoc() {
  const d = doc.value
  layers = d.layers as any
  activeLayerId = d.activeLayerId
  nextLayerId = Math.max(...d.layers.map(l => l.id), 0) + 1
  strokeHistory = d.layers[activeLayerId]?.strokes || []
  components.value = d.shapes.map(c => ({ type: c.type, x: c.x, y: c.y, size: c.size, cylinderRadius: (c as any).cylinderRadius, coneRadius: (c as any).coneRadius, coneTip: (c as any).coneTip, cuboidVectors: c.cuboidVectors, text: (c as any).text, textFont: (c as any).textFont, textColor: (c as any).textColor }))
  // 切换文档/图层：重置书写与便签状态，重建对象与便签组
  writingMode.value = false
  currentGroupId.value = null
  clearNoteSelection()
  buildObjects()
}
rebindDoc()

// 监听 components / strokeHistory 变化，重建对象列表
watch([() => components.value.length, () => strokeHistory.length], () => { nextTick(() => buildObjects()) })

// props.project 初始为空，loadProjects 完成后才赋值——保存当前到新 key，无需重建
watch(() => props.project, (p, prev) => {
  if (p && !prev) {
    // 将当前内容保存到新项目 key 下
    autoSaveCurrent()
    syncTabsMeta()
  }
})

function switchToDoc(idx: number) {
  if (idx === docIndex.value || idx < 0 || idx >= docs.length) return
  // 保存当前 tab 状态
  const cur = doc.value
  cur.activeLayerId = activeLayerId
  // 切换
  docIndex.value = idx
  rebindDoc()
  if (sctx && dctx) {
    redrawStrokes()
    dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H)
    drawOrigin()
    for (const c of components.value) { if (c.cuboidVectors) { drawCuboidFromVectors(dctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec) } else if (c.cylinderRadius) { drawCylinder2D(dctx, c.x, c.y, c.cylinderRadius, c.size || 50) } else if (c.coneRadius && c.coneTip) { if (c.type === 'rcone') { drawRightCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y) } else { drawCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip) } } else if (c.type === 'text') { drawComponent(dctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor) } else { drawComponent(dctx, c.type, c.x, c.y, c.size) } }
  }
  hasInk.value = checkHasInk()
  hasDesign.value = components.value.length > 0
}

function initLayers() {
  if (!layers.length) {
    const config = SCENES[doc.value.meta.scene]
    const defaults = config.defaultLayers.map((l, i) => ({
      id: i, name: l.name, visible: true, locked: l.locked || false, strokes: [] as StrokeDataType[],
    }))
    layers.splice(0, layers.length, ...defaults)
    activeLayerId = 0
    nextLayerId = defaults.length
  }
  const active = layers.find(l => l.id === activeLayerId)
  strokeHistory = active ? active.strokes : layers[0].strokes
  activeLayerId = active ? activeLayerId : layers[0].id
  doc.value.activeLayerId = activeLayerId
}

// 从所有可见图层全量重绘到表达层。指定 currentIndex 时活跃图层的该笔画用快速路径
function redrawStrokes(currentIndex?: number) {
  if (!sctx) return
  sctx.clearRect(0, 0, W, H)
  // 便签背景：先铺所有可见图层里便签组的底色（按笔画出现顺序，后建的便签在上）
  const bgAcc = new Map<string, { minX: number; minY: number; maxX: number; maxY: number }>()
  for (const layer of layers) {
    if (!layer.visible) continue
    for (const s of layer.strokes) {
      if (!s.groupId) continue
      let a = bgAcc.get(s.groupId)
      if (!a) { a = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }; bgAcc.set(s.groupId, a) }
      const bb = strokeBBox(s.points, s.width)
      a.minX = Math.min(a.minX, bb.x); a.minY = Math.min(a.minY, bb.y)
      a.maxX = Math.max(a.maxX, bb.x + bb.w); a.maxY = Math.max(a.maxY, bb.y + bb.h)
    }
  }
  for (const [, a] of bgAcc) {
    const x = a.minX - NOTE_PAD, y = a.minY - NOTE_PAD
    const w = a.maxX - a.minX + NOTE_PAD * 2, h = a.maxY - a.minY + NOTE_PAD * 2
    sctx.save()
    sctx.fillStyle = NOTE_BG
    sctx.strokeStyle = NOTE_BORDER
    sctx.lineWidth = 1.5
    sctx.beginPath()
    sctx.roundRect(x, y, w, h, 10)
    sctx.fill()
    sctx.stroke()
    sctx.restore()
  }
  for (const layer of layers) {
    if (!layer.visible) continue
    const isActive = layer.id === activeLayerId
    for (let i = 0; i < layer.strokes.length; i++) {
      const s = layer.strokes[i]
      if (s.points.length < 1) continue
      if (isActive && currentIndex !== undefined && i === currentIndex) {
        paintBezierStrokeFast(s.points, s.color, s.width, 1, 'round')
      } else {
        paintBezierStroke(s.points, s.color, s.width, 1, 'round')
      }
    }
  }
  // 重绘手势标记
  for (const g of gestures.value) {
    drawGestureMark(g.gesture, g.x, g.y)
  }
  // 选中便签高亮：蓝色虚线框 + 四角缩放柄（画在最上层）
  if (selectedNoteId.value) {
    const b = noteGroups.get(selectedNoteId.value)?.bbox
    if (b) drawNoteHighlight(b)
  }
}

/** 便签选中态：虚线包围框 + 四角方形缩放柄 */
function drawNoteHighlight(b: { x: number; y: number; w: number; h: number }) {
  if (!sctx) return
  const x = b.x - NOTE_PAD, y = b.y - NOTE_PAD
  const w = b.w + NOTE_PAD * 2, h = b.h + NOTE_PAD * 2
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 1.5
  sctx.setLineDash([6, 4])
  sctx.strokeRect(x, y, w, h)
  sctx.setLineDash([])
  const H = 9
  for (const [cx, cy] of [[x, y], [x + w, y], [x, y + h], [x + w, y + h]]) {
    sctx.fillStyle = '#ffffff'
    sctx.fillRect(cx - H / 2, cy - H / 2, H, H)
    sctx.strokeStyle = '#4a7dff'
    sctx.lineWidth = 1.5
    sctx.strokeRect(cx - H / 2, cy - H / 2, H, H)
  }
  sctx.restore()
}
let ghostPos = { x: 0, y: 0 }

// === 初始化 ===
function resizeCanvas() {
  // 大工作区画布：6000×4000 设计空间，CSS 裁剪 + 平移/缩放自由导航
  W = WORKSPACE_W
  H = WORKSPACE_H
  const pw = Math.round(W * DPR), ph = Math.round(H * DPR)
  // 设置 canvas 像素密度和 CSS 尺寸
  for (const c of [designCanvas.value, sketchCanvas.value, previewCanvas.value]) {
    if (c) { c.width = pw; c.height = ph; c.style.width = W + 'px'; c.style.height = H + 'px' }
  }
  // 同步 zoom-layer 和 design-layer 尺寸
  const zl = sketchCanvas.value?.parentElement as HTMLElement
  if (zl) { zl.style.width = W + 'px'; zl.style.height = H + 'px' }
  const dl = designCanvas.value?.parentElement as HTMLElement
  if (dl) { dl.style.width = W + 'px'; dl.style.height = H + 'px' }
  // 首次初始化时居中画布
  if (panX.value === -1 && panY.value === -1) {
    const wrap = zl?.parentElement as HTMLElement
    if (wrap) {
      panX.value = Math.round((wrap.clientWidth - W) / 2)
      panY.value = Math.round((wrap.clientHeight - H) / 2)
    } else {
      panX.value = 0; panY.value = 0
    }
  }
  if (dctx) { dctx.setTransform(DPR, 0, 0, DPR, 0, 0); dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H) }
  if (sctx) { sctx.setTransform(DPR, 0, 0, DPR, 0, 0) }
  drawOrigin()
  // 尺寸变化后从 strokeHistory 全量重绘
  redrawStrokes()
  if (dctx && components.value.length) {
    for (const c of components.value) { if (c.cuboidVectors) { drawCuboidFromVectors(dctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec) } else if (c.cylinderRadius) { drawCylinder2D(dctx, c.x, c.y, c.cylinderRadius, c.size || 50) } else if (c.coneRadius && c.coneTip) { if (c.type === 'rcone') { drawRightCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y) } else { drawCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip) } } else if (c.type === 'text') { drawComponent(dctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor) } else { drawComponent(dctx, c.type, c.x, c.y, c.size) } }
  }
}

function drawOrigin() {
  if (!dctx) return
  const cx = W / 2, cy = H / 2
  const step = 200
  const dd = doc.value
  const is3D = dd?.meta?.scene === '3d'
  dctx.save()

  // 网格线
  dctx.strokeStyle = '#f0f0f5'
  dctx.lineWidth = 1
  dctx.beginPath()
  for (let x = cx % step; x < W; x += step) {
    dctx.moveTo(x, 0); dctx.lineTo(x, H)
  }
  for (let y = cy % step; y < H; y += step) {
    dctx.moveTo(0, y); dctx.lineTo(W, y)
  }
  dctx.stroke()

  // 坐标轴
  dctx.strokeStyle = '#c7cdd6'
  dctx.lineWidth = 1.5
  dctx.beginPath()
  dctx.moveTo(0, cy); dctx.lineTo(W, cy)   // X 轴（右）
  dctx.moveTo(cx, 0); dctx.lineTo(cx, H)   // Y 轴（上）
  if (is3D) {
    // Z 轴：等轴测左下 30°，延伸到画布边缘
    const dzx = -Math.cos(Math.PI / 6)  // ≈ -0.866
    const dzy = Math.sin(Math.PI / 6)    // ≈ 0.5
    // 算交到左边(x=0)或底边(y=H)的距离
    const tl = cx / Math.abs(dzx)         // 到左边缘
    const tb = (H - cy) / dzy             // 到底边缘
    const zl = Math.min(tl, tb)
    const zx = cx + dzx * zl, zy = cy + dzy * zl
    dctx.moveTo(cx, cy); dctx.lineTo(zx, zy)
  }
  dctx.stroke()

  // X 轴箭头
  dctx.fillStyle = '#c7cdd6'
  dctx.beginPath(); dctx.moveTo(W - 12, cy); dctx.lineTo(W - 22, cy - 5); dctx.lineTo(W - 22, cy + 5); dctx.closePath(); dctx.fill()
  // Y 轴箭头
  dctx.beginPath(); dctx.moveTo(cx, 12); dctx.lineTo(cx - 5, 22); dctx.lineTo(cx + 5, 22); dctx.closePath(); dctx.fill()
  // Z 轴箭头
  if (is3D) {
    const dzx = -Math.cos(Math.PI / 6)
    const dzy = Math.sin(Math.PI / 6)
    const tl = cx / Math.abs(dzx)
    const tb = (H - cy) / dzy
    const zl = Math.min(tl, tb)
    const zx = cx + dzx * zl, zy = cy + dzy * zl
    // 箭头：沿方向反推
    dctx.beginPath()
    dctx.moveTo(zx, zy)
    dctx.lineTo(zx + 12 * dzx + 6 * dzy, zy + 12 * dzy - 6 * dzx)
    dctx.lineTo(zx + 12 * dzx - 6 * dzy, zy + 12 * dzy + 6 * dzx)
    dctx.closePath(); dctx.fill()
  }

  // 刻度与标签
  dctx.fillStyle = '#b0b8c1'
  dctx.font = '11px sans-serif'
  dctx.textAlign = 'center'
  dctx.textBaseline = 'top'
  for (let x = cx - Math.floor(cx / step) * step; x < W; x += step) {
    if (Math.abs(x - cx) < 1) continue
    const v = Math.round(x - cx)
    dctx.beginPath(); dctx.moveTo(x, cy - 4); dctx.lineTo(x, cy + 4); dctx.stroke()
    dctx.fillText(String(v), x, cy + 6)
  }
  for (let y = cy - Math.floor(cy / step) * step; y < H; y += step) {
    if (Math.abs(y - cy) < 1) continue
    const v = Math.round(cy - y)
    dctx.beginPath(); dctx.moveTo(cx - 4, y); dctx.lineTo(cx + 4, y); dctx.stroke()
    dctx.fillText(String(v), cx + 6, y - 6)
  }

  // 中心圆点
  dctx.fillStyle = '#9aa3b0'
  dctx.beginPath(); dctx.arc(cx, cy, 4, 0, Math.PI * 2); dctx.fill()

  // 轴标签
  dctx.fillStyle = '#8892a0'
  dctx.font = 'bold 13px sans-serif'
  dctx.textBaseline = 'middle'
  dctx.textAlign = 'left'
  dctx.fillText('X', W - 30, cy + 18)
  dctx.textAlign = 'center'
  dctx.fillText('Y', cx, 28)
  if (is3D) {
    dctx.textAlign = 'right'
    dctx.textBaseline = 'top'
    const dzx = -Math.cos(Math.PI / 6)
    const dzy = Math.sin(Math.PI / 6)
    const tl = cx / Math.abs(dzx)
    const tb = (H - cy) / dzy
    const zl = Math.min(tl, tb)
    const zx = cx + dzx * zl - 12, zy = cy + dzy * zl + 4
    dctx.fillText('Z', zx, zy)
  }

  dctx.restore()
}

function setupCanvas() {
  dctx = designCanvas.value?.getContext('2d') || null
  sctx = sketchCanvas.value?.getContext('2d') || null
  pctx = previewCanvas.value?.getContext('2d') || null
  resizeCanvas()
  if (sctx) {
    sctx.lineCap = 'round'
    sctx.lineJoin = 'round'
    sctx.strokeStyle = '#e11d48'  // 表达层用红色（区别于设计层）
    sctx.lineWidth = 2.5
  }
  if (dctx) {
    dctx.lineCap = 'round'
    dctx.lineJoin = 'round'
    dctx.strokeStyle = '#111'
  }
}

let _lastPos = { x: 0, y: 0 }
function lastPointerPos() { return _lastPos }

function getPos(e: PointerEvent) {
  // 用外层非变换容器 (sketch-canvas-wrap) 作坐标系，手动逆变换
  // CSS: translate(panX,panY) scale(zoom); 逆: (visual - pan) / zoom
  const wrapEl = sketchCanvas.value!.parentElement!.parentElement as HTMLElement
  const wrapRect = wrapEl.getBoundingClientRect()
  const vx = e.clientX - wrapRect.left
  const vy = e.clientY - wrapRect.top
  const raw = {
    x: (vx - panX.value) / zoom.value,
    y: (vy - panY.value) / zoom.value,
    pressure: e.pressure > 0 ? e.pressure : 0.5,
  }
  _lastPos = raw
  return raw
}

// === 设计层缩放 ===
// 缩放由 CSS transform 驱动：canvas 保持原生分辨率，视觉缩放/平移完全由 CSS 处理
// 故 zoom/pan 变化无需重绘 canvas——CSS 层已覆盖视觉效果
// 缩放以原点（坐标轴交点）为锚点，保持原点在视口中的位置不动
function applyZoom(newZoom: number) {
  const oldZoom = zoom.value
  const cx = W / 2, cy = H / 2
  panX.value = cx * (oldZoom - newZoom) + panX.value
  panY.value = cy * (oldZoom - newZoom) + panY.value
  zoom.value = newZoom
}
function zoomIn() { applyZoom(Math.min(ZOOM_MAX, zoom.value * 1.2)) }
function zoomOut() { applyZoom(Math.max(ZOOM_MIN, zoom.value / 1.2)) }
function onZoomSlider(e: Event) {
  const v = Number((e.target as HTMLInputElement).value) / 100
  applyZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v)))
}
function zoomReset() {
  zoom.value = 1
  const zl = sketchCanvas.value?.parentElement?.parentElement as HTMLElement
  if (zl) { panX.value = Math.round((zl.clientWidth - W) / 2); panY.value = Math.round((zl.clientHeight - H) / 2) }
  else { panX.value = 0; panY.value = 0 }
}
let _zoomAcc = 1
let _zoomRaf: number | null = null
function onWheel(e: WheelEvent) {
  // 触摸板双指缩放产生大量小步长事件，鼠标滚轮产生大步长事件
  // 用指数衰减将 deltaY 映射为连续缩放因子，rAF 节流到每帧只应用一次
  const factor = Math.exp(-e.deltaY / 800)
  _zoomAcc *= factor
  if (_zoomRaf === null) {
    _zoomRaf = requestAnimationFrame(() => {
      applyZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom.value * _zoomAcc)))
      _zoomAcc = 1
      _zoomRaf = null
    })
  }
}

// === 组件绘制（设计层） ===
function drawComponent(c2: CanvasRenderingContext2D, type: string, x: number, y: number, size = 44, textOverride?: string, fontOverride?: string, colorOverride?: string) {
  const s = ALL_SHAPES.find(s => s.type === type)
  if (!s && type !== 'text') return
  c2.save()
  c2.globalAlpha = 0.92
  c2.lineWidth = 2

  if (type === 'text') {
    const txt = textOverride || ''
    const font = fontOverride || textSettings.value.font
    const color = colorOverride || textSettings.value.color
    c2.font = font
    c2.fillStyle = color
    c2.textAlign = 'left'
    c2.textBaseline = 'top'
    c2.fillText(txt, x, y)
    c2.restore()
    hasDesign.value = true
    return
  }

  if (s.category === 'mechanical') {
    c2.fillStyle = '#eef2ff'
    c2.strokeStyle = '#4a7dff'
    c2.beginPath(); c2.arc(x, y, size / 2, 0, Math.PI * 2); c2.fill(); c2.stroke()
    c2.fillStyle = '#4a7dff'
    c2.font = `${Math.floor(size * 0.5)}px serif`
    c2.textAlign = 'center'; c2.textBaseline = 'middle'
    c2.fillText(s.icon, x, y - 2)
    c2.font = '10px sans-serif'
    c2.fillText(s.name, x, y + size * 0.42)
  } else if (s.category === '2d') {
    draw2DShape(c2, type, x, y, size)
  } else if (s.category === '3d') {
    draw3DShape(c2, type, x, y, size)
  }

  c2.restore()
  hasDesign.value = true
}

// 平面几何绘制
function draw2DShape(c2: CanvasRenderingContext2D, type: string, x: number, y: number, size: number) {
  const r = size / 2
  c2.fillStyle = '#f0f4ff'
  c2.strokeStyle = '#4a7dff'
  c2.beginPath()
  switch (type) {
    case 'circle':
      c2.arc(x, y, r * 0.8, 0, Math.PI * 2)
      break
    case 'square':
      c2.rect(x - r * 0.75, y - r * 0.75, r * 1.5, r * 1.5)
      break
    case 'triangle':
      c2.moveTo(x, y - r * 0.85)
      c2.lineTo(x - r * 0.85, y + r * 0.65)
      c2.lineTo(x + r * 0.85, y + r * 0.65)
      c2.closePath()
      break
    case 'diamond':
      c2.moveTo(x, y - r * 0.85)
      c2.lineTo(x + r * 0.65, y)
      c2.lineTo(x, y + r * 0.85)
      c2.lineTo(x - r * 0.65, y)
      c2.closePath()
      break
    case 'pentagon': {
      const n = 5
      for (let i = 0; i < n; i++) {
        const a = (Math.PI * 2 * i) / n - Math.PI / 2
        const px = x + Math.cos(a) * r * 0.8, py = y + Math.sin(a) * r * 0.8
        i === 0 ? c2.moveTo(px, py) : c2.lineTo(px, py)
      }
      c2.closePath()
      break
    }
    case 'hexagon': {
      const n = 6
      for (let i = 0; i < n; i++) {
        const a = (Math.PI * 2 * i) / n - Math.PI / 2
        const px = x + Math.cos(a) * r * 0.8, py = y + Math.sin(a) * r * 0.8
        i === 0 ? c2.moveTo(px, py) : c2.lineTo(px, py)
      }
      c2.closePath()
      break
    }
    case 'line':
      c2.moveTo(x - r * 0.8, y - r * 0.4)
      c2.lineTo(x + r * 0.8, y + r * 0.4)
      break
    case 'arrow':
      c2.moveTo(x - r * 0.8, y)
      c2.lineTo(x + r * 0.6, y)
      c2.moveTo(x + r * 0.3, y - r * 0.3)
      c2.lineTo(x + r * 0.6, y)
      c2.lineTo(x + r * 0.3, y + r * 0.3)
      break
  }
  c2.fill(); c2.stroke()
  // 名称标签
  c2.fillStyle = '#4a7dff'
  c2.font = '10px sans-serif'
  c2.textAlign = 'center'
  c2.fillText(compName(type), x, y + r + 12)
}

// 立体几何绘制（等轴测投影，支持旋转）
function draw3DShape(c2: CanvasRenderingContext2D, type: string, x: number, y: number, size: number, angle = 0) {
  const cx = x, cy = y
  const r = size / 2
  c2.save()
  c2.fillStyle = '#f0f4ff'
  c2.strokeStyle = '#4a7dff'
  if (angle !== 0) { c2.translate(cx, cy); c2.rotate(angle); c2.translate(-cx, -cy) }

  if (type === 'cube') {
    // 斜二测：正面真实正方形，深度 45° 缩半
    const s = size, d = s * 0.5 * 0.707  // 深度投影到 x/y 的分量
    // 7 个顶点：A(前下左) B(前下右) C(前上右) D(前上左) E(后下右) F(后上右) G(后上左)
    const A = { x: cx - s/2, y: cy + s/2 }
    const B = { x: cx + s/2, y: cy + s/2 }
    const C = { x: cx + s/2, y: cy - s/2 }
    const D = { x: cx - s/2, y: cy - s/2 }
    const E = { x: cx + s/2 + d, y: cy + s/2 - d }
    const F = { x: cx + s/2 + d, y: cy - s/2 - d }
    const G = { x: cx - s/2 + d, y: cy - s/2 - d }
    // 正面（ABCD 正方形）
    c2.beginPath(); c2.moveTo(A.x, A.y); c2.lineTo(B.x, B.y)
    c2.lineTo(C.x, C.y); c2.lineTo(D.x, D.y); c2.closePath(); c2.fill(); c2.stroke()
    // 顶面（D-C-F-G 平行四边形）
    c2.beginPath(); c2.moveTo(D.x, D.y); c2.lineTo(C.x, C.y)
    c2.lineTo(F.x, F.y); c2.lineTo(G.x, G.y); c2.closePath(); c2.fill(); c2.stroke()
    // 右侧面（B-E-F-C 平行四边形）
    c2.beginPath(); c2.moveTo(B.x, B.y); c2.lineTo(E.x, E.y)
    c2.lineTo(F.x, F.y); c2.lineTo(C.x, C.y); c2.closePath(); c2.fill(); c2.stroke()
  } else if (type === 'cuboid') {
    // 正面：矩形（宽=size, 高=size*0.7），深度同 45° 缩半
    const w = size, h = size * 0.7, d = w * 0.5 * 0.707
    const A = { x: cx - w/2, y: cy + h/2 }
    const B = { x: cx + w/2, y: cy + h/2 }
    const C = { x: cx + w/2, y: cy - h/2 }
    const D = { x: cx - w/2, y: cy - h/2 }
    const E = { x: cx + w/2 + d, y: cy + h/2 - d }
    const F = { x: cx + w/2 + d, y: cy - h/2 - d }
    const G = { x: cx - w/2 + d, y: cy - h/2 - d }
    c2.beginPath(); c2.moveTo(A.x, A.y); c2.lineTo(B.x, B.y)
    c2.lineTo(C.x, C.y); c2.lineTo(D.x, D.y); c2.closePath(); c2.fill(); c2.stroke()
    c2.beginPath(); c2.moveTo(D.x, D.y); c2.lineTo(C.x, C.y)
    c2.lineTo(F.x, F.y); c2.lineTo(G.x, G.y); c2.closePath(); c2.fill(); c2.stroke()
    c2.beginPath(); c2.moveTo(B.x, B.y); c2.lineTo(E.x, E.y)
    c2.lineTo(F.x, F.y); c2.lineTo(C.x, C.y); c2.closePath(); c2.fill(); c2.stroke()
  } else if (type === 'sphere') {
    // 球体画法：正圆 + 赤道纬线（前半实线+后半虚线穿过圆心）
    const R = r
    // 外轮廓正圆
    c2.beginPath(); c2.arc(cx, cy, R, 0, Math.PI * 2); c2.fill(); c2.stroke()
    // 赤道纬线：前半段实线（下方弧）+ 后半段虚线（上方弧/背面）
    c2.save()
    // 前半段实线弧：从左端穿过圆心下方到右端
    c2.beginPath()
    c2.moveTo(cx - R, cy)
    c2.quadraticCurveTo(cx, cy + R * 0.5, cx + R, cy)
    c2.stroke()
    // 后半段虚线弧：从右端穿过上方到左端（背面）
    c2.setLineDash([5, 4])
    c2.beginPath()
    c2.moveTo(cx + R, cy)
    c2.quadraticCurveTo(cx, cy - R * 0.5, cx - R, cy)
    c2.stroke()
    c2.restore()
  } else if (type === 'cylinder') {
    // 斜二测：正面矩形 + 上下面椭圆（正面圆真实）
    const ew = r * 0.8, eh = ew * 0.4
    const topY = cy - r * 0.6, botY = cy + r * 0.6
    // 底面椭圆（完整可见）
    c2.beginPath(); c2.ellipse(cx, botY, ew, eh, 0, 0, Math.PI*2); c2.fill(); c2.stroke()
    // 顶面椭圆
    c2.beginPath(); c2.ellipse(cx, topY, ew, eh, 0, 0, Math.PI*2); c2.fill(); c2.stroke()
    // 矩形主体
    c2.beginPath(); c2.moveTo(cx - ew, botY); c2.lineTo(cx - ew, topY)
    c2.lineTo(cx + ew, topY); c2.lineTo(cx + ew, botY)
    c2.closePath(); c2.fill(); c2.stroke()
    // 重新画底面椭圆（在主体上覆盖绘制以保持完整轮廓）
    c2.beginPath(); c2.ellipse(cx, botY, ew, eh, 0, 0, Math.PI*2); c2.fill(); c2.stroke()
  } else if (type === 'cone') {
    // 斜二测：底面椭圆 + 两条切到顶点的切线
    const ew = r * 0.65, eh = ew * 0.35
    const botY = cy + r * 0.5, tipY = cy - r * 0.8
    // 底面
    c2.beginPath(); c2.ellipse(cx, botY, ew, eh, 0, 0, Math.PI*2); c2.fill(); c2.stroke()
    // 锥面三角形
    c2.beginPath(); c2.moveTo(cx - ew, botY); c2.lineTo(cx, tipY)
    c2.lineTo(cx + ew, botY); c2.closePath(); c2.fill(); c2.stroke()
    // 底面重绘（覆盖锥面底线，保持椭圆轮廓）
    c2.beginPath(); c2.ellipse(cx, botY, ew, eh, 0, 0, Math.PI*2); c2.fill(); c2.stroke()
  } else if (type === 'pyramid') {
    // 斜二测：正方形底面 + 深度方向缩半 + 棱汇聚到顶点
    const s = size * 0.6
    const d = s * 0.5 * 0.707, tipY = cy - r * 0.7
    const A = { x: cx - s/2, y: cy + s/2 }
    const B = { x: cx + s/2, y: cy + s/2 }
    const C = { x: cx + s/2 + d, y: cy + s/2 - d }
    const D = { x: cx - s/2 + d, y: cy + s/2 - d }
    // 底面
    c2.beginPath(); c2.moveTo(A.x, A.y); c2.lineTo(B.x, B.y)
    c2.lineTo(C.x, C.y); c2.lineTo(D.x, D.y); c2.closePath(); c2.fill(); c2.stroke()
    // 前面三角形
    c2.beginPath(); c2.moveTo(A.x, A.y); c2.lineTo(B.x, B.y)
    c2.lineTo(cx, tipY); c2.closePath(); c2.fill(); c2.stroke()
    // 右面三角形
    c2.beginPath(); c2.moveTo(B.x, B.y); c2.lineTo(C.x, C.y)
    c2.lineTo(cx, tipY); c2.closePath(); c2.fill(); c2.stroke()
    // 后面三角形
    c2.beginPath(); c2.moveTo(C.x, C.y); c2.lineTo(D.x, D.y)
    c2.lineTo(cx, tipY); c2.closePath(); c2.fill(); c2.stroke()
    // 左面三角形
    c2.beginPath(); c2.moveTo(D.x, D.y); c2.lineTo(A.x, A.y)
    c2.lineTo(cx, tipY); c2.closePath(); c2.fill(); c2.stroke()
  }
  c2.restore()
  c2.fillStyle = '#4a7dff'
  c2.font = '10px sans-serif'
  c2.textAlign = 'center'
  c2.fillText(compName(type), cx, cy + r + 12)
}

// 立体几何拖拽预览（虚线 + 起点圆点）
function draw3DPreviewLine(start: { x: number; y: number }, end: { x: number; y: number }) {
  if (!sctx) return
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.setLineDash([6, 4])
  sctx.beginPath()
  sctx.moveTo(start.x, start.y)
  sctx.lineTo(end.x, end.y)
  sctx.stroke()
  sctx.setLineDash([])
  sctx.fillStyle = '#4a7dff'
  sctx.beginPath(); sctx.arc(start.x, start.y, 4, 0, Math.PI * 2); sctx.fill()
  sctx.restore()
}

// cuboid 三笔预览：已定边实线 + 当前拖拽成形预览
function drawCuboidPreview(start: {x:number;y:number}, cursor: {x:number;y:number}) {
  if (!sctx) return
  const anc = cuboidAnchor!
  const phase = cuboidPhase.value
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.fillStyle = '#4a7dff'

  if (phase === 1) {
    // ① 横划：虚线从锚点→光标
    sctx.setLineDash([6, 4])
    sctx.beginPath()
    sctx.moveTo(anc.x, anc.y)
    sctx.lineTo(cursor.x, cursor.y)
    sctx.stroke()
    sctx.setLineDash([])
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 4, 0, Math.PI*2); sctx.fill()
  } else if (phase === 2) {
    const ft = cuboidFrontTop!
    const B = { x: anc.x + ft.x, y: anc.y + ft.y }
    // 当前拖拽向量正交化（只取垂直于第一边的高度分量）
    const raw = { x: cursor.x - anc.x, y: cursor.y - anc.y }
    const ov = orthoProject(raw, ft)
    const D = { x: anc.x + ov.x, y: anc.y + ov.y }
    const C = { x: B.x + ov.x, y: B.y + ov.y }
    // 第一边实线
    sctx.setLineDash([])
    sctx.beginPath()
    sctx.moveTo(anc.x, anc.y); sctx.lineTo(B.x, B.y)
    sctx.stroke()
    // 矩形虚线预览
    sctx.setLineDash([6, 4])
    sctx.beginPath()
    sctx.moveTo(anc.x, anc.y); sctx.lineTo(D.x, D.y)
    sctx.lineTo(C.x, C.y); sctx.lineTo(B.x, B.y)
    sctx.stroke()
    // 起笔引导线（起笔点→光标）
    if (start.x !== anc.x || start.y !== anc.y) {
      sctx.beginPath()
      sctx.moveTo(start.x, start.y); sctx.lineTo(cursor.x, cursor.y)
      sctx.stroke()
    }
    sctx.setLineDash([])
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 4, 0, Math.PI*2); sctx.fill()
  } else if (phase === 3) {
    const ft = cuboidFrontTop!, fl = cuboidFrontLeft!
    const B = { x: anc.x + ft.x, y: anc.y + ft.y }
    const D = { x: anc.x + fl.x, y: anc.y + fl.y }
    const C = { x: anc.x + ft.x + fl.x, y: anc.y + ft.y + fl.y }
    // 当前深度向量（从锚点算）
    const vx = cursor.x - anc.x, vy = cursor.y - anc.y
    const A2 = { x: anc.x + vx, y: anc.y + vy }
    const B2 = { x: B.x + vx, y: B.y + vy }
    const C2 = { x: C.x + vx, y: C.y + vy }
    const D2 = { x: D.x + vx, y: D.y + vy }
    // 正面实线
    sctx.setLineDash([])
    sctx.beginPath()
    sctx.moveTo(anc.x, anc.y); sctx.lineTo(B.x, B.y)
    sctx.lineTo(C.x, C.y); sctx.lineTo(D.x, D.y)
    sctx.closePath()
    sctx.stroke()
    // 深度棱线 + 背面（虚线）
    sctx.setLineDash([6, 4])
    sctx.beginPath()
    sctx.moveTo(anc.x, anc.y); sctx.lineTo(A2.x, A2.y)
    sctx.moveTo(B.x, B.y); sctx.lineTo(B2.x, B2.y)
    sctx.moveTo(C.x, C.y); sctx.lineTo(C2.x, C2.y)
    sctx.moveTo(D.x, D.y); sctx.lineTo(D2.x, D2.y)
    sctx.stroke()
    sctx.beginPath()
    sctx.moveTo(A2.x, A2.y); sctx.lineTo(B2.x, B2.y)
    sctx.lineTo(C2.x, C2.y); sctx.lineTo(D2.x, D2.y)
    sctx.closePath()
    sctx.stroke()
    // 起笔引导线
    if (start.x !== anc.x || start.y !== anc.y) {
      sctx.beginPath()
      sctx.moveTo(start.x, start.y); sctx.lineTo(cursor.x, cursor.y)
      sctx.stroke()
    }
    sctx.setLineDash([])
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 4, 0, Math.PI*2); sctx.fill()
  }

  sctx.restore()
}

// cylinder 两笔预览
function drawCylinderPreview(start: {x:number;y:number}, cursor: {x:number;y:number}) {
  if (!sctx) return
  const anc = cylinderAnchor.value!
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.fillStyle = '#4a7dff'

  if (cylinderPhase.value === 1) {
    // 椭圆预览：虚线椭圆 + 半径线
    const r = Math.hypot(cursor.x - anc.x, cursor.y - anc.y)
    const eh = r * 0.4
    sctx.setLineDash([6, 4])
    sctx.beginPath(); sctx.ellipse(anc.x, anc.y, r, eh, 0, 0, Math.PI * 2); sctx.stroke()
    sctx.beginPath(); sctx.moveTo(anc.x, anc.y); sctx.lineTo(cursor.x, cursor.y); sctx.stroke()
    sctx.setLineDash([])
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 3, 0, Math.PI * 2); sctx.fill()
  } else if (cylinderPhase.value === 2) {
    const R = cylinderRadius.value
    const eh = R * 0.4
    const botCX = anc.x, botCY = cursor.y
    // 顶面椭圆已在画布上（第一笔保留），不重画
    // 高度虚线
    sctx.setLineDash([6, 4])
    sctx.beginPath(); sctx.moveTo(anc.x, anc.y); sctx.lineTo(botCX, botCY); sctx.stroke()
    // 两侧竖线（实线）
    sctx.setLineDash([])
    sctx.beginPath()
    sctx.moveTo(anc.x - R, anc.y); sctx.lineTo(botCX - R, botCY)
    sctx.moveTo(anc.x + R, anc.y); sctx.lineTo(botCX + R, botCY)
    sctx.stroke()
    // 底面椭圆：下半实线（可见）+ 上半虚线（背面）
    sctx.setLineDash([])
    sctx.beginPath(); sctx.ellipse(botCX, botCY, R, eh, 0, 0, Math.PI); sctx.stroke()
    sctx.setLineDash([5, 4])
    sctx.beginPath(); sctx.ellipse(botCX, botCY, R, eh, 0, -Math.PI, 0); sctx.stroke()
    sctx.setLineDash([])
    sctx.fillStyle = '#4a7dff'
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 3, 0, Math.PI * 2); sctx.fill()
  }

  sctx.restore()
}

// cylinder 最终绘制：顶面实线 + 底椭圆半虚半实（投影遮挡） + 两侧竖线实线（轮廓线）
function drawCylinder2D(c2: CanvasRenderingContext2D, cx: number, cy: number, r: number, h: number) {
  // 锚点为顶面中心，底面垂直向下
  const topCX = cx, topCY = cy
  const botCX = cx, botCY = cy + h
  const eh = r * 0.4  // 椭圆短半轴（长轴水平）

  c2.save()
  c2.fillStyle = '#f0f4ff'
  c2.strokeStyle = '#4a7dff'
  c2.lineWidth = 2

  // 底面椭圆：后半弧虚线（投影遮挡）+ 前半弧实线（可见）
  c2.setLineDash([5, 4])
  c2.beginPath(); c2.ellipse(botCX, botCY, r, eh, 0, -Math.PI, 0); c2.stroke()
  c2.setLineDash([])
  c2.beginPath(); c2.ellipse(botCX, botCY, r, eh, 0, 0, Math.PI); c2.stroke()

  // 两侧竖线
  c2.beginPath()
  c2.moveTo(topCX - r, topCY); c2.lineTo(botCX - r, botCY)
  c2.moveTo(topCX + r, topCY); c2.lineTo(botCX + r, botCY)
  c2.stroke()

  // 顶面椭圆（最后画，覆盖竖线上端）
  c2.beginPath(); c2.ellipse(topCX, topCY, r, eh, 0, 0, Math.PI * 2); c2.fill(); c2.stroke()

  c2.restore()
  c2.fillStyle = '#4a7dff'
  c2.font = '10px sans-serif'
  c2.textAlign = 'center'
  c2.fillText('圆柱', cx, cy + r + 12)

  hasDesign.value = true
}

// cone 两笔预览
function drawConePreview(start: {x:number;y:number}, cursor: {x:number;y:number}) {
  if (!sctx) return
  const anc = coneAnchor.value!
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.fillStyle = '#4a7dff'

  if (conePhase.value === 1) {
    const r = Math.hypot(cursor.x - anc.x, cursor.y - anc.y)
    const eh = r * 0.4
    sctx.setLineDash([6, 4])
    sctx.beginPath(); sctx.ellipse(anc.x, anc.y, r, eh, 0, 0, Math.PI * 2); sctx.stroke()
    sctx.beginPath(); sctx.moveTo(anc.x, anc.y); sctx.lineTo(cursor.x, cursor.y); sctx.stroke()
    sctx.setLineDash([])
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 3, 0, Math.PI * 2); sctx.fill()
  } else if (conePhase.value === 2) {
    const R = coneRadius.value
    const eh = R * 0.4
    const tipX = cursor.x, tipY = cursor.y
    // 轴线——顶点到圆心（虚线，被锥体遮挡）
    sctx.setLineDash([5, 4])
    sctx.beginPath(); sctx.moveTo(tipX, tipY); sctx.lineTo(anc.x, anc.y); sctx.stroke()
    // 底面椭圆：后半弧虚线（被遮挡）+ 前半弧实线（可见）
    sctx.beginPath(); sctx.ellipse(anc.x, anc.y, R, eh, 0, -Math.PI, 0); sctx.stroke()
    sctx.setLineDash([])
    sctx.beginPath(); sctx.ellipse(anc.x, anc.y, R, eh, 0, 0, Math.PI); sctx.stroke()
    // 两条轮廓线（可见→实线）
    sctx.beginPath()
    sctx.moveTo(anc.x - R, anc.y); sctx.lineTo(tipX, tipY)
    sctx.moveTo(anc.x + R, anc.y); sctx.lineTo(tipX, tipY)
    sctx.stroke()
    // 顶点圆点
    sctx.beginPath(); sctx.arc(tipX, tipY, 3, 0, Math.PI * 2); sctx.fill()
    // 圆心
    sctx.beginPath(); sctx.arc(anc.x, anc.y, 3, 0, Math.PI * 2); sctx.fill()
  }

  sctx.restore()
}

// cone 最终绘制：轴线虚线（遮挡）+ 底椭圆后半虚前半实（投影遮挡）+ 轮廓线实线
function drawCone2D(c2: CanvasRenderingContext2D, cx: number, cy: number, r: number, tip: {x:number;y:number}) {
  const eh = r * 0.4
  c2.save()
  c2.strokeStyle = '#4a7dff'
  c2.lineWidth = 2

  // 轴线虚线（被锥体遮挡）
  c2.setLineDash([5, 4])
  c2.beginPath(); c2.moveTo(tip.x, tip.y); c2.lineTo(cx, cy); c2.stroke()

  // 底面椭圆：后半弧虚线（投影遮挡）+ 前半弧实线（可见）
  c2.setLineDash([5, 4])
  c2.beginPath(); c2.ellipse(cx, cy, r, eh, 0, -Math.PI, 0); c2.stroke()
  c2.setLineDash([])
  c2.beginPath(); c2.ellipse(cx, cy, r, eh, 0, 0, Math.PI); c2.fillStyle = '#f0f4ff'; c2.fill(); c2.stroke()

  // 两条轮廓线到顶点（可见→实线）
  c2.beginPath()
  c2.moveTo(cx - r, cy); c2.lineTo(tip.x, tip.y)
  c2.moveTo(cx + r, cy); c2.lineTo(tip.x, tip.y)
  c2.stroke()

  // 底面实线重绘（覆盖切线起点）
  c2.beginPath(); c2.ellipse(cx, cy, r, eh, 0, 0, Math.PI); c2.stroke()

  // 顶点圆点
  c2.fillStyle = '#4a7dff'
  c2.setLineDash([])
  c2.beginPath(); c2.arc(tip.x, tip.y, 3, 0, Math.PI * 2); c2.fill()
  // 圆心圆点
  c2.beginPath(); c2.arc(cx, cy, 3, 0, Math.PI * 2); c2.fill()

  c2.restore()
  c2.fillStyle = '#4a7dff'
  c2.font = '10px sans-serif'
  c2.textAlign = 'center'
  c2.fillText('圆锥', cx, cy + r + 12)

  hasDesign.value = true
}

// 正圆锥一笔预览：轴线虚线 + 底椭圆虚线 + 两条轮廓线实线 + 顶点+圆心
function drawRightConePreview(start: {x:number;y:number}, cursor: {x:number;y:number}) {
  if (!sctx) return
  const tip = start  // 起点是顶点
  const dx = cursor.x - tip.x
  const dy = cursor.y - tip.y
  const r = Math.abs(dx)
  const h = Math.abs(dy)
  const cx = tip.x            // 底面圆心 x = 顶点投影
  const cy = tip.y + h         // 底面圆心 y
  const eh = r * 0.4
  const mirrorX = cx - (cursor.x - cx)  // 另一侧底边点
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.fillStyle = '#4a7dff'

  // 底面椭圆虚线
  sctx.setLineDash([6, 4])
  sctx.beginPath(); sctx.ellipse(cx, cy, r, eh, 0, 0, Math.PI * 2); sctx.stroke()

  // 轴线——顶点到圆心（虚线）
  sctx.beginPath(); sctx.moveTo(tip.x, tip.y); sctx.lineTo(cx, cy); sctx.stroke()

  // 对侧棱（轮廓线，可见→实线）
  sctx.setLineDash([])
  sctx.beginPath(); sctx.moveTo(tip.x, tip.y); sctx.lineTo(mirrorX, cy); sctx.stroke()

  // 当前棱——从顶点到光标
  sctx.beginPath(); sctx.moveTo(tip.x, tip.y); sctx.lineTo(cursor.x, cursor.y); sctx.stroke()

  // 顶点
  sctx.beginPath(); sctx.arc(tip.x, tip.y, 3, 0, Math.PI * 2); sctx.fill()

  // 底面圆心
  sctx.beginPath(); sctx.arc(cx, cy, 3, 0, Math.PI * 2); sctx.fill()

  sctx.restore()
}

// 正圆锥最终绘制：轴线虚线 + 底椭圆半虚半实（投影遮挡） + 轮廓线实线
function drawRightCone2D(c2: CanvasRenderingContext2D, cx: number, cy: number, r: number, tipX: number, tipY: number) {
  const eh = r * 0.4
  c2.save()
  c2.strokeStyle = '#4a7dff'
  c2.lineWidth = 2

  // 轴线虚线（被锥体遮挡）
  c2.setLineDash([5, 4])
  c2.beginPath(); c2.moveTo(tipX, tipY); c2.lineTo(cx, cy); c2.stroke()

  // 底面椭圆：后半弧虚线（投影遮挡）+ 前半弧实线（可见）
  c2.setLineDash([5, 4])
  c2.beginPath(); c2.ellipse(cx, cy, r, eh, 0, -Math.PI, 0); c2.stroke()
  c2.setLineDash([])
  c2.beginPath(); c2.ellipse(cx, cy, r, eh, 0, 0, Math.PI); c2.fillStyle = '#f0f4ff'; c2.fill(); c2.stroke()

  // 两条轮廓线到顶点（可见→实线）
  c2.beginPath()
  c2.moveTo(cx - r, cy); c2.lineTo(tipX, tipY)
  c2.moveTo(cx + r, cy); c2.lineTo(tipX, tipY)
  c2.stroke()

  // 底面实线重绘
  c2.beginPath(); c2.ellipse(cx, cy, r, eh, 0, 0, Math.PI); c2.stroke()

  // 顶点 + 圆心
  c2.fillStyle = '#4a7dff'
  c2.setLineDash([])
  c2.beginPath(); c2.arc(tipX, tipY, 3, 0, Math.PI * 2); c2.fill()
  c2.beginPath(); c2.arc(cx, cy, 3, 0, Math.PI * 2); c2.fill()

  c2.restore()
  c2.fillStyle = '#4a7dff'
  c2.font = '10px sans-serif'
  c2.textAlign = 'center'
  c2.fillText('正圆锥', cx, cy + r + 12)

  hasDesign.value = true
}

// cuboid 三向量最终绘制
function drawCuboidFromVectors(
  c2: CanvasRenderingContext2D,
  anchor: {x:number;y:number},
  frontTop: {x:number;y:number},
  frontLeft: {x:number;y:number},
  depthVec: {x:number;y:number}
) {
  const A = anchor
  const B = { x: A.x + frontTop.x, y: A.y + frontTop.y }
  const C = { x: A.x + frontTop.x + frontLeft.x, y: A.y + frontTop.y + frontLeft.y }
  const D = { x: A.x + frontLeft.x, y: A.y + frontLeft.y }
  const A2 = { x: A.x + depthVec.x, y: A.y + depthVec.y }
  const B2 = { x: B.x + depthVec.x, y: B.y + depthVec.y }
  const C2 = { x: C.x + depthVec.x, y: C.y + depthVec.y }
  const D2 = { x: D.x + depthVec.x, y: D.y + depthVec.y }

  c2.save()
  c2.fillStyle = '#f0f4ff'
  c2.strokeStyle = '#4a7dff'
  c2.lineWidth = 2

  // 正面
  c2.beginPath(); c2.moveTo(A.x, A.y); c2.lineTo(B.x, B.y)
  c2.lineTo(C.x, C.y); c2.lineTo(D.x, D.y); c2.closePath(); c2.fill(); c2.stroke()
  // 顶面
  c2.beginPath(); c2.moveTo(A.x, A.y); c2.lineTo(B.x, B.y)
  c2.lineTo(B2.x, B2.y); c2.lineTo(A2.x, A2.y); c2.closePath(); c2.fill(); c2.stroke()
  // 右侧面
  c2.beginPath(); c2.moveTo(B.x, B.y); c2.lineTo(C.x, C.y)
  c2.lineTo(C2.x, C2.y); c2.lineTo(B2.x, B2.y); c2.closePath(); c2.fill(); c2.stroke()

  c2.restore()
  // 名称标签
  c2.fillStyle = '#4a7dff'
  c2.font = '10px sans-serif'
  c2.textAlign = 'center'
  const cx = (A.x + B.x + C.x + D.x + A2.x + B2.x + C2.x + D2.x) / 8
  const cy = (A.y + B.y + C.y + D.y + A2.y + B2.y + C2.y + D2.y) / 8
  const r = Math.max(Math.hypot(frontTop.x, frontTop.y), Math.hypot(frontLeft.x, frontLeft.y), Math.hypot(depthVec.x, depthVec.y)) / 2
  c2.fillText('长方体', cx, cy + r + 12)

  hasDesign.value = true
}

function placeComponent(x: number, y: number, cursor?: { x: number; y: number }) {
  if (!placing.value || !dctx) return
  const sized = TWO_D_SIZED.has(placing.value)
  const size = sized && cursor ? Math.max(10, Math.hypot(cursor.x - x, cursor.y - y) * 2) : 44
  const type = placing.value
  components.value.push({ type, x, y, size })
  drawComponent(dctx, type, x, y, size)
  // 两笔式：第一点定中心，移动实时预览，第二点确认尺寸后立即结束画图（同立体几何收尾），清预览层退出放置
  placeAnchor.value = null
  placing.value = null
  if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
  scheduleAutoSave()
}

function removeComponent(idx: number) {
  components.value.splice(idx, 1)
}

function componentListText(): string {
  if (!components.value.length) return ''
  return '\n\n[组件标注] ' + components.value.map(c =>
    `${compName(c.type)}@(${Math.round(c.x)},${Math.round(c.y)})`
  ).join('; ')
}

// 手势清单文本（发送给 AI 的语义化指令）
function gestureListText(): string {
  if (!gestures.value.length) return ''
  return '\n\n[手势指令] ' + gestures.value.map(g => g.note).join('; ')
}

// 调色板语义（发送给 AI，说明颜色=意图的约定）
function paletteSemanticText(): string {
  return '\n\n[颜色约定] ' + PALETTE.map(c => `${c.name}(${c.color})`).join('；') +
    '。用户在画布上用不同颜色表达不同意图，请按颜色语义解读批注。'
}

// 场景描述：把画布内容整理成 AI 可理解的文字，配合 PNG 一起发送
function buildSceneDescription(): string {
  const parts: string[] = ['【画布结构化数据 → 3D 工程坐标】\n']

  // 计算所有组件的包围盒中心，用于坐标归一化
  let cx = 0, cy = 0
  if (components.value.length) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const c of components.value) {
      if (c.cuboidVectors) {
        const pts = [c, {x: c.x + c.cuboidVectors.frontTop.x, y: c.y + c.cuboidVectors.frontTop.y}]
        for (const p of pts) { minX = Math.min(minX, p.x); minY = Math.min(minY, p.y); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y) }
      } else if (c.coneRadius && c.coneTip) {
        minX = Math.min(minX, c.x, c.coneTip.x); minY = Math.min(minY, c.y, c.coneTip.y)
        maxX = Math.max(maxX, c.x, c.coneTip.x); maxY = Math.max(maxY, c.y, c.coneTip.y)
      } else {
        const s = (c.size || 44)
        minX = Math.min(minX, c.x - s); minY = Math.min(minY, c.y - s)
        maxX = Math.max(maxX, c.x + s); maxY = Math.max(maxY, c.y + s)
      }
    }
    if (isFinite(minX)) { cx = Math.round((minX + maxX) / 2); cy = Math.round((minY + maxY) / 2) }
  }

  // 坐标映射：画布X→3D_X，画布Y(翻转)→3D_Z（垂直高度），3D_Y=0（正面深度）
  // 每个组件输出 X、Y(深度)、Z(高度) 三维坐标
  parts.push('坐标映射规则：画布X→X轴(mm)；画布Y轴倒转后→Z轴(垂直高度,mm)；Y轴(深度)=0mm。尺寸单位为mm。\n')
  
  if (components.value.length) {
    const items: string[] = []
    for (const c of components.value) {
      const type = compName(c.type)
      const dx = Math.round(c.x - cx)          // 3D X
      const dz = Math.round(cy - c.y)          // 3D Z（高度，画布Y翻转）
      if (c.cuboidVectors) {
        const ft = c.cuboidVectors.frontTop
        const fl = c.cuboidVectors.frontLeft
        const dv = c.cuboidVectors.depthVec
        const w = Math.hypot(ft.x, ft.y)       // 宽 → X
        const h = Math.hypot(fl.x, fl.y)       // 高 → Z
        const d = Math.hypot(dv.x, dv.y)       // 深 → Y
        const angle = Math.round(Math.atan2(ft.y, ft.x) * 180 / Math.PI)
        items.push(`${type}: 锚点(X=${dx}, Y=0, Z=${dz}) 宽${Math.round(w)}(X) 高${Math.round(h)}(Z) 深${Math.round(d)}(Y) 朝向${angle}°`)
      } else if (c.cylinderRadius) {
        // 圆柱：半径在 XY 平面，高沿 Z
        items.push(`${type}: 底面圆心(X=${dx}, Y=0, Z=${dz}) 半径${Math.round(c.cylinderRadius)}(XZ平面) 高${Math.round(c.size||50)}(Z轴)`)
      } else if (c.coneRadius && c.coneTip) {
        const tz = Math.round(cy - c.coneTip.y)  // 顶点 Z
        const tx = Math.round(c.coneTip.x - cx)  // 顶点 X
        items.push(`${type}: 底面圆心(X=${dx}, Y=0, Z=${dz}) 半径${Math.round(c.coneRadius)} 顶点(X=${tx}, Y=0, Z=${tz})`)
      } else if (c.type === 'text') {
        items.push(`文字「${(c.text||'').slice(0,20)}」: (X=${dx}, Z=${dz})`)
      } else {
        // 3D 实体：尺寸为直径/边长
        const s = Math.round(c.size || 44)
        items.push(`${type}: 中心(X=${dx}, Y=0, Z=${dz}) 尺寸${s}(边长/直径)`)
      }
    }
    parts.push(`已放置 ${components.value.length} 个组件：\n${items.map(i => `  - ${i}`).join('\n')}`)
  }

  // 笔迹
  const totalStrokes = layers.reduce((sum, l) => sum + l.strokes.length, 0)
  if (totalStrokes) {
    const allColors = new Set<string>()
    for (const l of layers) for (const s of l.strokes) allColors.add(s.color)
    parts.push(`\n手绘笔迹：${totalStrokes} 笔，${allColors.size} 种颜色`)
  }

  // 手势
  if (gestures.value.length) {
    parts.push(`\n手势标记：${gestures.value.map(g => g.note).join('；')}`)
  }

  parts.push(`\n${paletteSemanticText().trim()}`)
  parts.push('\n坐标系：X轴水平向右，Y轴垂直向上。坐标单位与画布像素一致。')

  return parts.join('\n')
}

// === 形状命令解析 ===
// 支持：立方体/正方体/cube、长方体 200 at 300,200、圆 at 100,200、球体 半径50 位置 300,200 等
const SHAPE_ALIASES: Record<string, string> = {
  '立方体': 'cube', '正方体': 'cube', 'cube': 'cube',
  '长方体': 'cuboid', 'cuboid': 'cuboid',
  '球体': 'sphere', '球': 'sphere', 'sphere': 'sphere',
  '圆柱': 'cylinder', '圆柱体': 'cylinder', 'cylinder': 'cylinder',
  '圆锥': 'cone', '圆锥体': 'cone', 'cone': 'cone',
  '棱锥': 'pyramid', 'pyramid': 'pyramid',
  '圆': 'circle', '圆形': 'circle', 'circle': 'circle',
  '矩形': 'square', '正方形': 'square', 'rect': 'square', 'square': 'square',
  '三角形': 'triangle', 'triangle': 'triangle',
  '菱形': 'diamond', 'diamond': 'diamond',
  '五边形': 'pentagon', 'pentagon': 'pentagon',
  '六边形': 'hexagon', 'hexagon': 'hexagon',
  '直线': 'line', 'line': 'line',
  '箭头': 'arrow', 'arrow': 'arrow',
  '齿轮': 'gear', 'gear': 'gear',
  '铰链': 'hinge', 'hinge': 'hinge',
  '推杆': 'actuator', 'actuator': 'actuator',
  '电机': 'motor', 'motor': 'motor',
  '轴承': 'bearing', 'bearing': 'bearing',
  '丝杠': 'screw', 'screw': 'screw',
  '滑轨': 'slider', 'slider': 'slider',
  '滚轮': 'wheel', 'wheel': 'wheel',
}

function parseShapeCommand(text: string): { type: string; size?: number; x?: number; y?: number; msg: string } | null {
  const t = text.trim()
  // 找形状关键词
  let matchedType = ''
  let matchedKeyword = ''
  for (const [kw, type] of Object.entries(SHAPE_ALIASES)) {
    if (t.startsWith(kw)) {
      if (kw.length > matchedKeyword.length) { matchedType = type; matchedKeyword = kw }
    }
  }
  if (!matchedType) return null

  let rest = t.slice(matchedKeyword.length).trim()

  // 解析尺寸：数字 or 半径50 or 边长100
  let size: number | undefined
  const sizeMatch = rest.match(/^(\d+)/)
  if (sizeMatch) {
    size = parseInt(sizeMatch[1])
    rest = rest.slice(sizeMatch[0].length).trim()
  }
  // 也支持 "半径50" "边长100" 格式
  const radiusMatch = rest.match(/^(?:半径|边长|大小|size)?\s*(\d+)/i)
  if (!size && radiusMatch) {
    size = parseInt(radiusMatch[1])
    rest = rest.slice(radiusMatch[0].length).trim()
  }

  // 解析位置：at x,y / 在 x,y / 位置 x,y / x,y
  let x: number | undefined, y: number | undefined
  const posMatch = rest.match(/(?:at|在|位置|@)?\s*(\d+)\s*[,，]\s*(\d+)/i)
  if (posMatch) {
    x = parseInt(posMatch[1])
    y = parseInt(posMatch[2])
  }

  const shapeName = ALL_SHAPES.find(s => s.type === matchedType)?.name || matchedType
  let msg = `✅ 已识别：${shapeName}`
  if (size) msg += `，大小 ${size}`
  if (x !== undefined) msg += `，位置 (${x}, ${y})`
  if (x === undefined) msg += ' → 请在画布上点击/拖拽放置'

  return { type: matchedType, size, x, y, msg }
}

// === 图层管理 ===
function addLayer() {
  const id = nextLayerId++
  layers.push({ id, name: '自定义', visible: true, locked: false, strokes: [] })
  activeLayerId = id
  doc.value.activeLayerId = id
  strokeHistory = layers[layers.length - 1].strokes
}

function deleteLayer(id: number) {
  if (layers.length <= 1) return  // 至少保留一个图层
  layers = layers.filter(l => l.id !== id)
  if (activeLayerId === id) {
    activeLayerId = layers[0].id
    strokeHistory = layers[0].strokes
  }
  redrawStrokes()
}

function renameLayer(id: number, name: string) {
  const layer = layers.find(l => l.id === id)
  if (layer) layer.name = name
}

function toggleLayer(id: number) {
  const layer = layers.find(l => l.id === id)
  if (layer) layer.visible = !layer.visible
  redrawStrokes()
}

function selectLayer(id: number) {
  if (activeLayerId === id) return
  activeLayerId = id
  doc.value.activeLayerId = id
  const layer = layers.find(l => l.id === id)
  if (layer) strokeHistory = layer.strokes
}

// === 组件面板 ===
function onCompCategoryChange() {
  if (compCategory.value) {
    exitPlacing()  // 切换分类不残留旧放置状态
    toolMode.value = 'comp'
  } else {
    toolMode.value = 'pen'
    placing.value = null
    threeDPlacing.value = null
    if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
    cuboidPhase.value = 0; cuboidAnchor = null; cuboidFrontTop = null; cuboidFrontLeft = null; cuboidPreviewSnap = null
    cylinderPhase.value = 0; cylinderAnchor.value = null; cylinderRadius.value = 0
    conePhase.value = 0; coneAnchor.value = null; coneRadius.value = 0
  }
}
function startPlacing(type: string) {
  const s = ALL_SHAPES.find(s => s.type === type)
  if (s && s.category === '3d') {
    if (type === 'cuboid') { if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height); cuboidPhase.value = 0; cuboidAnchor = null; cuboidFrontTop = null; cuboidFrontLeft = null; cuboidPreviewSnap = null }
    if (type === 'cylinder') { cylinderPhase.value = 0; cylinderAnchor.value = null; cylinderRadius.value = 0 }
    if (type === 'cone') { conePhase.value = 0; coneAnchor.value = null; coneRadius.value = 0 }
    threeDPlacing.value = type
    placing.value = null
    return
  }
  if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
  cuboidPhase.value = 0; cuboidAnchor = null; cuboidFrontTop = null; cuboidFrontLeft = null; cuboidPreviewSnap = null
  threeDPlacing.value = null
  placing.value = type
}

function cancel3DPlacing() {
  if (threeDPlacing.value === 'cuboid') {
    cuboidPhase.value = 0
    cuboidAnchor = null
    cuboidFrontTop = null
    cuboidFrontLeft = null
    cuboidPreviewSnap = null
  }
  if (threeDPlacing.value === 'cylinder') {
    cylinderPhase.value = 0
    cylinderAnchor.value = null
    cylinderRadius.value = 0
  }
  if (threeDPlacing.value === 'cone') {
    conePhase.value = 0
    coneAnchor.value = null
    coneRadius.value = 0
  }
  threeDPlacing.value = null
  threeDStart = null
  threeDDragging = false
  redrawStrokes()
}

function onKeyDown(e: KeyboardEvent) {
  // 输入框内按键不触发画布快捷键（避免输入文字时误删便签）
  const t = e.target as HTMLElement
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNoteId.value) {
    e.preventDefault()
    deleteSelectedNote()
    return
  }
  if (e.key === 'Escape') {
    if (writingMode.value) { toggleWriting(); return }
    if (threeDPlacing.value) { cancel3DPlacing(); return }
    if (selecting.value && selectMode.value === 'lasso') { cancelLasso(); return }
    if (placing.value) {
      if (placeAnchor.value) { placeAnchor.value = null; if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height); return }  // 取消锚点，保留放置态
      placing.value = null; return  // 退出放置
    }
    if (toolMode.value === 'shape' && shapeStart) {
      // 取消进行中的形状（拖拽中/多边形中途）
      shapeStart = null
      shapePoints = []
      if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
      return
    }
  }
}

function updateGhost(raw: { x: number; y: number }) {
  if (!ghostEl.value || !sketchCanvas.value) return
  const wrap = sketchCanvas.value.parentElement as HTMLElement
  if (!wrap) return
  const cRect = sketchCanvas.value.getBoundingClientRect()
  const px = raw.x * (cRect.width / W)
  const py = raw.y * (cRect.height / H)
  ghostEl.value.style.left = px + 'px'
  ghostEl.value.style.top = py + 'px'
}

// === 框选 / 自由圈选 ===
function startSelect(raw: { x: number; y: number }) {
  selecting.value = true
  if (selectMode.value === 'lasso') {
    lassoPoints = [{ x: raw.x, y: raw.y }]
    if (sctx) lassoSnapshot = sctx.getImageData(0, 0, sctx.canvas.width, sctx.canvas.height)
    return
  }
  selStart = { x: raw.x, y: raw.y }
  selRect.value = { x: raw.x, y: raw.y, w: 0, h: 0 }
}
function updateSelect(raw: { x: number; y: number }) {
  if (selectMode.value === 'lasso') {
    if (!lassoPoints.length) return
    lassoPoints.push({ x: raw.x, y: raw.y })
    drawLassoPreview()
    return
  }
  if (!selStart) return
  selRect.value = {
    x: Math.min(selStart.x, raw.x),
    y: Math.min(selStart.y, raw.y),
    w: Math.abs(raw.x - selStart.x),
    h: Math.abs(raw.y - selStart.y),
  }
}
function drawLassoPreview() {
  if (!sctx || !lassoSnapshot) return
  sctx.putImageData(lassoSnapshot, 0, 0)
  if (lassoPoints.length < 2) return
  sctx.save()
  sctx.strokeStyle = '#4a7dff'
  sctx.lineWidth = 2
  sctx.lineCap = 'round'
  sctx.lineJoin = 'round'
  sctx.setLineDash([6, 3])
  sctx.beginPath()
  sctx.moveTo(lassoPoints[0].x, lassoPoints[0].y)
  for (let i = 1; i < lassoPoints.length; i++) sctx.lineTo(lassoPoints[i].x, lassoPoints[i].y)
  sctx.stroke()
  sctx.restore()
}
function endSelect() {
  selecting.value = false
  if (selectMode.value === 'lasso') {
    if (sctx && lassoSnapshot) sctx.putImageData(lassoSnapshot, 0, 0)
    lassoSnapshot = null
    if (lassoPoints.length > 3) {
      const closed = [...lassoPoints, lassoPoints[0]]
      const minX = Math.min(...closed.map(p => p.x))
      const minY = Math.min(...closed.map(p => p.y))
      const maxX = Math.max(...closed.map(p => p.x))
      const maxY = Math.max(...closed.map(p => p.y))
      const w = maxX - minX, h = maxY - minY
      if (w > 8 && h > 8) {
        selRect.value = { x: minX, y: minY, w, h }
        // 圈选对象：选中包围盒与圈选区域相交的对象
        buildObjects()
        selectedIds.value = []
        for (const o of objects) o.selected = false
        for (const o of objects) {
          if (o.bbox.x + o.bbox.w < minX || o.bbox.x > maxX || o.bbox.y + o.bbox.h < minY || o.bbox.y > maxY) continue
          o.selected = true
          selectedIds.value.push(o.id)
        }
        if (selectedIds.value.length > 0) {
          errorMsg.value = `已圈选 ${selectedIds.value.length} 个对象，可拖拽移动`
          if (dctx) redrawAllDesign()
        } else {
          errorMsg.value = `已自由圈选区域，无对象被选中`
        }
      }
    }
    lassoPoints = []
    return
  }
  // 矩形框选
  if (selRect.value && selRect.value.w > 8 && selRect.value.h > 8) {
    const r = selRect.value
    buildObjects()
    selectedIds.value = []
    for (const o of objects) o.selected = false
    for (const o of objects) {
      if (o.bbox.x + o.bbox.w < r.x || o.bbox.x > r.x + r.w || o.bbox.y + o.bbox.h < r.y || o.bbox.y > r.y + r.h) continue
      o.selected = true
      selectedIds.value.push(o.id)
    }
    if (selectedIds.value.length > 0) {
      errorMsg.value = `已框选 ${selectedIds.value.length} 个对象，可拖拽移动`
      if (dctx) redrawAllDesign()
    } else {
      errorMsg.value = `已框选区域，无对象被选中`
    }
  }
  selStart = null
  selRect.value = null
}
function cancelLasso() {
  if (sctx && lassoSnapshot) sctx.putImageData(lassoSnapshot, 0, 0)
  lassoSnapshot = null
  lassoPoints = []
  selecting.value = false
}

// === 指针事件（表达层） ===
function onPointerDown(e: PointerEvent) {
  if (!sctx) return
  e.preventDefault()
  // setPointerCapture 可能失败（模拟事件/特殊环境），失败不影响绘制
  try { sketchCanvas.value!.setPointerCapture(e.pointerId) } catch {}
  const raw = getPos(e)

  // 立体几何拖拽
  if (threeDPlacing.value) {
    if (threeDPlacing.value === 'cuboid') {
      if (cuboidPhase.value === 0) {
        cuboidPhase.value = 1
        cuboidAnchor = { x: raw.x, y: raw.y }
        cuboidFrontTop = null; cuboidFrontLeft = null
      }
      threeDStart = (cuboidPhase.value === 1 || cuboidPhase.value === 3) && cuboidAnchor
        ? { x: cuboidAnchor.x, y: cuboidAnchor.y }
        : { x: raw.x, y: raw.y }
      threeDDragging = true
      return
    }
    if (threeDPlacing.value === 'cylinder') {
      if (cylinderPhase.value === 0) {
        cylinderPhase.value = 1
        cylinderAnchor.value = { x: raw.x, y: raw.y }
        cylinderRadius.value = 0
      }
      threeDStart = { x: raw.x, y: raw.y }
      threeDDragging = true
      return
    }
    if (threeDPlacing.value === 'cone') {
      if (conePhase.value === 0) {
        conePhase.value = 1
        coneAnchor.value = { x: raw.x, y: raw.y }
        coneRadius.value = 0
      }
      threeDStart = { x: raw.x, y: raw.y }
      threeDDragging = true
      return
    }
    if (threeDPlacing.value === 'rcone') {
      threeDStart = { x: raw.x, y: raw.y }
      threeDDragging = true
      return
    }
    if (threeDPlacing.value === 'text') {
      const txt = prompt('请输入文字', '文字')
      if (txt && dctx) {
        components.value.push({
          type: 'text', x: raw.x, y: raw.y,
          text: txt, textFont: textSettings.value.font, textColor: textSettings.value.color
        })
        drawComponent(dctx, 'text', raw.x, raw.y, 0, txt, textSettings.value.font, textSettings.value.color)
        redrawStrokes()
        scheduleAutoSave()
      }
      return
    }
    threeDStart = { x: raw.x, y: raw.y }
    threeDDragging = true
    return
  }

  // 组件放置：2d 尺寸型两笔式（第一击定中心，第二击确认尺寸）；其余一键放置
  if (placing.value) {
    if (TWO_D_SIZED.has(placing.value)) {
      if (placeAnchor.value) placeComponent(placeAnchor.value.x, placeAnchor.value.y, raw)
      else placeAnchor.value = { x: raw.x, y: raw.y }
    } else {
      placeComponent(raw.x, raw.y)
    }
    return
  }
  // 便签与对象的选择/移动（书写模式下跳过，直接落笔）
  if (toolMode.value === 'pen' && !threeDPlacing.value && !writingMode.value) {
    // 便签四角缩放柄：命中则开始缩放
    const handle = noteHandleAt(raw.x, raw.y)
    if (handle && selectedNoteId.value) {
      const b = noteGroups.get(selectedNoteId.value)!.bbox
      const cx = b.x + b.w / 2, cy = b.y + b.h / 2
      noteScaleStart = { cx, cy, startDist: Math.max(1, Math.hypot(raw.x - cx, raw.y - cy)) }
      return
    }
    // 便签整体命中：已选中→按下即拖拽；未选中→笔画优先（轻点才选中，见 onPointerUp）
    const nid = noteAt(raw.x, raw.y)
    if (nid && selectedNoteId.value === nid) {
      objDragStart = { x: raw.x, y: raw.y }
      objDragOffsets = new Map()
      for (const id of selectedIds.value) objDragOffsets.set(id, { dx: 0, dy: 0 })
      isDragging.value = true
      return
    }
    if (nid) {
      penTapPending = { kind: 'note', id: nid }
      penTapStart = { x: raw.x, y: raw.y }
    }
    const hit = objectAt(raw.x, raw.y)
    if (hit) {
      if (hit.selected) {
        // 点击已选中对象 → 准备拖拽移动
        objDragStart = { x: raw.x, y: raw.y }
        objDragOffsets = new Map()
        dragInfo.dx = 0; dragInfo.dy = 0
        dragInfo.x = hit.pose.x; dragInfo.y = hit.pose.y
        dragInfo.a = hit.pose.a; dragInfo.b = hit.pose.b; dragInfo.c = hit.pose.c
        isDragging.value = true
        for (const id of selectedIds.value) {
          const o = objects.find(ob => ob.id === id)
          if (o) objDragOffsets.set(id, { dx: 0, dy: 0 })
        }
        return
      } else {
        // 未选中对象：笔画优先——先落笔；抬笔时若为轻点则选中该对象（见 onPointerUp）
        penTapPending = { kind: 'obj', id: hit.id }
        penTapStart = { x: raw.x, y: raw.y }
      }
    }
    // 点击空白区 → 取消选中
    if (selectedIds.value.length > 0) {
      for (const o of objects) o.selected = false
      selectedIds.value = []
      selectedNoteId.value = null
      if (dctx) { redrawAllDesign() }
    }
  }
  // 移动画布模式
  if (toolMode.value === 'pan') {
    panning.value = true
    panStart = { x: e.clientX, y: e.clientY }
    panOrigin = { x: panX.value, y: panY.value }
    return
  }
  // 框选模式
  if (toolMode.value === 'select') {
    startSelect(raw)
    return
  }
  // 形状模式
  if (toolMode.value === 'shape') {
    shapePointerDown(raw)
    return
  }
  // 橡皮擦模式
  if (toolMode.value === 'eraser') {
    erasing = true
    lastX = raw.x
    lastY = raw.y
    eraserPoints.push({ x: raw.x, y: raw.y })
    applyEraserDot(raw)
    return
  }

  drawing = true
  currentStroke = [{ x: raw.x, y: raw.y }]
  lastX = raw.x
  lastY = raw.y
  lastPressure = raw.pressure
  // 撤销栈：记录笔画数据（轻量），不保存整幅位图（性能优化，避免大图卡顿）
  const bw = brushWidth(raw.pressure)
  strokeHistory.push({ color: penColor.value, width: bw, points: [{ x: raw.x, y: raw.y }], groupId: writingMode.value ? (currentGroupId.value ?? undefined) : undefined })
  // 全量重绘：已完成笔画高画质，当前笔画快速路径
  redrawStrokes(strokeHistory.length - 1)
  hasInk.value = true
}

function onPointerMove(e: PointerEvent) {
  if (!sctx) return
  const raw = getPos(e)
  // 便签缩放拖动：以中心等比缩放
  if (noteScaleStart && selectedNoteId.value) {
    const cx = noteScaleStart.cx, cy = noteScaleStart.cy
    const dist = Math.hypot(raw.x - cx, raw.y - cy)
    applyNoteScale(selectedNoteId.value, cx, cy, Math.max(0.05, dist / noteScaleStart.startDist))
    return
  }
  // 立体几何拖拽预览（使用预览层，避免大画布 getImageData 卡顿）
  if (threeDDragging && threeDStart) {
    if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
    if (threeDPlacing.value === 'cuboid') {
      drawCuboidPreview(threeDStart, raw)
    } else if (threeDPlacing.value === 'cylinder') {
      drawCylinderPreview(threeDStart, raw)
    } else if (threeDPlacing.value === 'cone') {
      drawConePreview(threeDStart, raw)
    } else if (threeDPlacing.value === 'rcone') {
      drawRightConePreview(threeDStart, raw)
    } else {
      draw3DPreviewLine(threeDStart, raw)
    }
    return
  }
  // 对象拖拽移动
  if (objDragStart && selectedIds.value.length > 0) {
    const dx = raw.x - objDragStart.x, dy = raw.y - objDragStart.y
    moveSelected(dx, dy)
    objDragStart = { x: raw.x, y: raw.y }
    // 更新拖拽提示
    if (selectedIds.value.length > 0) {
      const first = objects.find(o => o.selected)
      if (first) {
        dragInfo.x = first.pose.x; dragInfo.y = first.pose.y
        dragInfo.a = first.pose.a; dragInfo.b = first.pose.b; dragInfo.c = first.pose.c
      }
      dragInfo.dx += dx; dragInfo.dy += dy
    }
    return
  }
  // 两笔式放置预览：锚点已定 → 预览层画形状 + 中心→光标辅助线
  if (placing.value && placeAnchor.value) {
    if (pctx) {
      pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
      const size = Math.max(10, Math.hypot(raw.x - placeAnchor.value.x, raw.y - placeAnchor.value.y) * 2)
      draw2DShape(pctx, placing.value, placeAnchor.value.x, placeAnchor.value.y, size)
      pctx.save()
      pctx.strokeStyle = '#4a7dff'; pctx.lineWidth = 1.5; pctx.setLineDash([6, 4])
      pctx.beginPath(); pctx.moveTo(placeAnchor.value.x, placeAnchor.value.y); pctx.lineTo(raw.x, raw.y); pctx.stroke()
      pctx.restore()
    }
    return
  }
  if (placing.value) { ghostPos = raw; updateGhost(raw); return }
  if (panning.value) {
    panX.value = panOrigin.x + (e.clientX - panStart.x) / zoom.value
    panY.value = panOrigin.y + (e.clientY - panStart.y) / zoom.value
    return
  }
  if (selecting.value) { updateSelect(raw); return }
  // 形状模式：拖动预览
  if (toolMode.value === 'shape' && shapeStart) {
    shapePointerMove(raw)
    lastX = raw.x
    lastY = raw.y
    return
  }
  // 橡皮擦：移动擦除
  if (toolMode.value === 'eraser' && erasing) {
    applyEraserStroke(raw)
    return
  }
  if (!drawing) return
  // 提笔后移动（buttons=0）绝不绘制：从机制上杜绝"提笔移动接着画"
  if (e.buttons === 0 && e.pressure === 0) {
    // 兜底：若 pointerup 事件丢失（笔拖出画布外等），这里自动复位绘制状态
    drawing = false
    return
  }
  e.preventDefault()
  // 累积采样点（抽稀：距离过近的点跳过，减少抖动）
  const lastPt = currentStroke[currentStroke.length - 1]
  if (lastPt) {
    const dx = raw.x - lastPt.x, dy = raw.y - lastPt.y
    if (dx * dx + dy * dy < 4) return  // <2px 跳过
  }
  currentStroke.push({ x: raw.x, y: raw.y })
  const pts = currentStroke
  // 同步更新撤销栈笔画（限长，避免数组过大）
  const last = strokeHistory[strokeHistory.length - 1]
  if (last && last.points.length < 300) last.points.push({ x: raw.x, y: raw.y })

  // 实时预览：全量重绘 + 当前笔画快速路径
  redrawStrokes(strokeHistory.length - 1)
  lastX = raw.x
  lastY = raw.y
  lastPressure = raw.pressure
}

// 快速路径版：整笔一条贝塞尔路径画完（实时预览用，无锥形，性能好）
function paintBezierStrokeFast(pts: { x: number; y: number }[], color: string, width: number, alpha: number, cap: CanvasLineCap) {
  if (!sctx || pts.length < 1) return
  sctx.save()
  sctx.globalAlpha = alpha
  sctx.lineCap = cap
  sctx.lineJoin = 'round'
  sctx.strokeStyle = color
  sctx.lineWidth = width
  sctx.beginPath()
  sctx.moveTo(pts[0].x, pts[0].y)
  if (pts.length === 1) {
    sctx.arc(pts[0].x, pts[0].y, Math.max(width / 2, 1), 0, Math.PI * 2)
    sctx.fill()
  } else if (pts.length === 2) {
    sctx.lineTo(pts[1].x, pts[1].y)
    sctx.stroke()
  } else {
    for (let i = 0; i < pts.length - 2; i++) {
      const p = pts[i]
      sctx.quadraticCurveTo(p.x, p.y, (p.x + pts[i + 1].x) / 2, (p.y + pts[i + 1].y) / 2)
    }
    const lp = pts[pts.length - 1]
    const pp = pts[pts.length - 2]
    sctx.quadraticCurveTo(pp.x, pp.y, lp.x, lp.y)
    sctx.stroke()
  }
  sctx.restore()
}

// 整笔中点贝塞尔绘制（从起点到终点一次性画完，无段间拼接）
// 带锥形笔锋（taper）：起笔收笔渐细、中段饱满，美化手写观感
function paintBezierStroke(pts: { x: number; y: number }[], color: string, width: number, alpha: number, cap: CanvasLineCap) {
  if (!sctx || pts.length < 1) return
  sctx.save()
  sctx.globalAlpha = alpha
  sctx.lineCap = 'round'
  sctx.lineJoin = 'round'
  sctx.strokeStyle = color

  if (pts.length === 1) {
    // 单点：实心圆点
    sctx.lineWidth = width
    sctx.beginPath()
    sctx.arc(pts[0].x, pts[0].y, Math.max(width / 2, 1), 0, Math.PI * 2)
    sctx.fill()
    sctx.restore()
    return
  }

  // 把中点贝塞尔路径采样成密集点列（保留光滑 + 支持逐段变宽）
  const samples = sampleBezierPath(pts)
  const n = samples.length
  if (n < 2) { sctx.restore(); return }

  // 等宽绘制：不做首末锥形美化，按原始笔迹等宽输出（2026-09-02 去美化）
  sctx.lineWidth = width
  sctx.beginPath()
  sctx.moveTo(samples[0].x, samples[0].y)
  for (let i = 1; i < n; i++) sctx.lineTo(samples[i].x, samples[i].y)
  sctx.stroke()
  sctx.restore()
}

// 中点贝塞尔 → 密集采样点列（每段二次曲线采样 3 个子段）
function sampleBezierPath(pts: { x: number; y: number }[]): { x: number; y: number }[] {
  const curves: { p0: { x: number; y: number }; c: { x: number; y: number }; p1: { x: number; y: number } }[] = []
  if (pts.length === 2) {
    curves.push({ p0: pts[0], c: pts[0], p1: pts[1] })
  } else {
    // 第一段：从起点到 mid(p0,p1)，控制点 p0
    curves.push({ p0: pts[0], c: pts[0], p1: midPt(pts[0], pts[1]) })
    // 中间段：mid(pi-1,pi) → mid(pi,pi+1)，控制点 pi
    for (let i = 1; i < pts.length - 2; i++) {
      curves.push({ p0: midPt(pts[i - 1], pts[i]), c: pts[i], p1: midPt(pts[i], pts[i + 1]) })
    }
    // 最后一段：mid(pn-2,pn-1) → 终点，控制点 pn-2
    const lp = pts[pts.length - 1], pp = pts[pts.length - 2]
    curves.push({ p0: midPt(pp, lp), c: pp, p1: lp })
  }
  const out: { x: number; y: number }[] = []
  for (const { p0, c, p1 } of curves) {
    for (let t = 0; t < 1; t += 1 / 3) {
      const mt = 1 - t
      out.push({
        x: mt * mt * p0.x + 2 * mt * t * c.x + t * t * p1.x,
        y: mt * mt * p0.y + 2 * mt * t * c.y + t * t * p1.y,
      })
    }
  }
  // 补终点
  const last = pts[pts.length - 1]
  out.push({ x: last.x, y: last.y })
  return out
}

function midPt(a: { x: number; y: number }, b: { x: number; y: number }) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}
// 正交投影：把 v 投影到 onto 的垂直方向上
function orthoProject(v: {x:number;y:number}, onto: {x:number;y:number}): {x:number;y:number} {
  const len = Math.hypot(onto.x, onto.y)
  if (len < 1) return v
  const perpX = -onto.y / len, perpY = onto.x / len
  const dot = v.x * perpX + v.y * perpY
  return { x: perpX * dot, y: perpY * dot }
}

// （直接绘制模式，无 rAF 合并；撤销栈已轻量化避免卡顿）

function onPointerUp() {
  // 便签缩放结束
  if (noteScaleStart) {
    noteScaleStart = null
    scheduleAutoSave()
    return
  }
  // 对象拖拽结束
  if (objDragStart) {
    objDragStart = null
    isDragging.value = false
    if (dctx) { buildObjects(); redrawAllDesign() }
    scheduleAutoSave()
    return
  }
  // 立体几何拖拽完成
  if (threeDDragging && threeDStart && threeDPlacing.value) {
    threeDDragging = false
    if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
    const raw = lastPointerPos()

    // rcone 一笔绘制：从顶点拖出斜棱，终点定底面半径与高度
    if (threeDPlacing.value === 'rcone') {
      threeDDragging = false
      const raw = lastPointerPos()
      const tip = threeDStart   // 起点=顶点
      const dx = raw.x - tip.x
      const dy = raw.y - tip.y
      const r = Math.abs(dx)
      const h = Math.abs(dy)
      if (r < 4 || h < 4) { threeDStart = null; return }
      const cx = tip.x, cy = tip.y + h  // 底面圆心=顶点在底面的投影
      if (dctx) {
        components.value.push({ type: 'rcone', x: cx, y: cy, size: h, coneRadius: r, coneTip: { x: tip.x, y: tip.y } })
        drawRightCone2D(dctx, cx, cy, r, tip.x, tip.y)
      }
      cuboidPreviewSnap = null
      threeDStart = null
      threeDPlacing.value = 'rcone'  // 保持模式，继续画
      redrawStrokes()
      scheduleAutoSave()
      return
    }

    // cone 两笔绘制
    if (threeDPlacing.value === 'cone') {
      const anc = coneAnchor.value!
      if (conePhase.value === 1) {
        const r = Math.hypot(raw.x - anc.x, raw.y - anc.y)
        if (r < 4) { threeDStart = null; return }
        coneRadius.value = r
        conePhase.value = 2
        threeDStart = null
        if (sctx) {
          sctx.save()
          sctx.strokeStyle = '#4a7dff'; sctx.lineWidth = 2; sctx.setLineDash([])
          const eh = r * 0.4
          sctx.beginPath(); sctx.ellipse(anc.x, anc.y, r, eh, 0, 0, Math.PI * 2); sctx.fillStyle = '#f0f4ff'; sctx.fill(); sctx.stroke()
          sctx.fillStyle = '#4a7dff'
          sctx.beginPath(); sctx.arc(anc.x, anc.y, 3, 0, Math.PI * 2); sctx.fill()
          sctx.restore()
        }
        if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
        cuboidPreviewSnap = null
        return
      } else if (conePhase.value === 2 && dctx) {
        const dx = raw.x - anc.x, dy = raw.y - anc.y
        const h = Math.hypot(dx, dy)
        if (h < 4) { threeDStart = null; return }
        const r = coneRadius.value
        // 顶点在圆心基础上偏移 dx,dy（上半部）或反向（下半部），取绝对值高度
        const tipX = anc.x + dx, tipY = anc.y + dy
        components.value.push({ type: 'cone', x: anc.x, y: anc.y, size: h, coneRadius: r, coneTip: { x: tipX, y: tipY } })
        drawCone2D(dctx, anc.x, anc.y, r, { x: tipX, y: tipY })
        conePhase.value = 0
        coneAnchor.value = null
        coneRadius.value = 0
        cuboidPreviewSnap = null
        threeDStart = null
        redrawStrokes()
        scheduleAutoSave()
        return
      }
      threeDStart = null
      return
    }

    // cylinder 两笔绘制
    if (threeDPlacing.value === 'cylinder') {
      const anc = cylinderAnchor.value!
      if (cylinderPhase.value === 1) {
        const r = Math.hypot(raw.x - anc.x, raw.y - anc.y)
        if (r < 4) { threeDStart = null; return }
        cylinderRadius.value = r
        cylinderPhase.value = 2
        threeDStart = null
        if (sctx) {
          sctx.save()
          sctx.strokeStyle = '#4a7dff'; sctx.lineWidth = 2; sctx.setLineDash([])
          const eh = r * 0.4
          sctx.beginPath(); sctx.ellipse(anc.x, anc.y, r, eh, 0, 0, Math.PI * 2); sctx.fillStyle = '#f0f4ff'; sctx.fill(); sctx.stroke()
          sctx.fillStyle = '#4a7dff'
          sctx.beginPath(); sctx.arc(anc.x, anc.y, 3, 0, Math.PI * 2); sctx.fill()
          sctx.restore()
        }
        if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
        cuboidPreviewSnap = null
        return
      } else if (cylinderPhase.value === 2 && dctx) {
        const h = Math.abs(raw.y - anc.y)
        if (h < 4) { threeDStart = null; return }
        const r = cylinderRadius.value
        components.value.push({ type: 'cylinder', x: anc.x, y: anc.y, size: h, cylinderRadius: r })
        drawCylinder2D(dctx, anc.x, anc.y, r, h)
        cylinderPhase.value = 0
        cylinderAnchor.value = null
        cylinderRadius.value = 0
        cuboidPreviewSnap = null
        threeDStart = null
        redrawStrokes()
        scheduleAutoSave()
        return
      }
      threeDStart = null
      return
    }

    // cuboid 三笔绘制
    if (threeDPlacing.value === 'cuboid') {
      // 向量始终从 cuboidAnchor 算，而非落笔点 threeDStart
      const anc = cuboidAnchor!
      const vx = raw.x - anc.x
      const vy = raw.y - anc.y
      const len = Math.hypot(vx, vy)
      if (len < 8) { threeDStart = null; return }
      if (cuboidPhase.value === 1) {
        cuboidFrontTop = { x: vx, y: vy }
        cuboidPhase.value = 2
        threeDStart = null
        // 保留第一边实线到 sctx
        if (sctx) {
          cuboidDrawSolidEdge(cuboidAnchor!, { x: cuboidAnchor!.x + cuboidFrontTop!.x, y: cuboidAnchor!.y + cuboidFrontTop!.y })
          sctx.beginPath(); sctx.arc(cuboidAnchor!.x, cuboidAnchor!.y, 4, 0, Math.PI*2)
          sctx.fillStyle = '#4a7dff'
          sctx.fill()
        }
        if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
        cuboidPreviewSnap = null
        return
      } else if (cuboidPhase.value === 2) {
        cuboidFrontLeft = orthoProject({ x: vx, y: vy }, cuboidFrontTop!)
        cuboidPhase.value = 3
        threeDStart = null
        // 画正面矩形实线到 sctx
        if (sctx) {
          cuboidDrawSolidRect(cuboidAnchor!, cuboidFrontTop!, cuboidFrontLeft!)
        }
        if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
        cuboidPreviewSnap = null
        return
      } else if (cuboidPhase.value === 3 && dctx) {
        const depthVec = { x: vx, y: vy }
        if (!cuboidFrontTop || !cuboidFrontLeft) { threeDStart = null; return }
        components.value.push({
          type: 'cuboid',
          x: cuboidAnchor!.x, y: cuboidAnchor!.y,
          size: 0,
          cuboidVectors: { frontTop: cuboidFrontTop, frontLeft: cuboidFrontLeft, depthVec }
        })
        drawCuboidFromVectors(dctx, cuboidAnchor!, cuboidFrontTop, cuboidFrontLeft, depthVec)
        // 重置，继续画下一个
        cuboidPhase.value = 0
        cuboidAnchor = null
        cuboidFrontTop = null
        cuboidFrontLeft = null
        cuboidPreviewSnap = null
        threeDStart = null
        redrawStrokes()
        scheduleAutoSave()
        return
      }
      threeDStart = null
      return
    }

    // 非 cuboid 立体几何
    const dx = raw.x - threeDStart.x
    const dy = raw.y - threeDStart.y
    const len = Math.hypot(dx, dy)
    if (len > 8 && dctx) {
      const angle = Math.atan2(dy, dx)
      const t = threeDPlacing.value
      const sz = len
      let cx = threeDStart.x
      let cy = threeDStart.y
      if (t === 'cube') {
        cx = threeDStart.x + sz / 2
        cy = threeDStart.y + sz / 2
      }
      components.value.push({ type: t, x: cx, y: cy, size: sz })
      draw3DShape(dctx, t, cx, cy, sz, angle)
    }
    threeDStart = null
    // 保持 threeDPlacing，继续画下一个（ESC 取消）
    redrawStrokes()
    scheduleAutoSave()
    return
  }
  // 关键：先复位 drawing（抬笔立即停止绘制，提笔后移动绝不再画）
  drawing = false
  erasing = false
  panning.value = false
  const wasPen = toolMode.value === 'pen'
  if (wasPen) {
    redrawStrokes()
    scheduleAutoSave()
    // 笔画优先的轻点判定：位移<6px 视为轻点→丢弃笔迹并选中目标；否则保留笔画（手写不被吞）
    if (penTapPending) {
      const pts = strokeHistory[strokeHistory.length - 1]?.points
      let isTap = false
      if (pts && pts.length) {
        isTap = true
        for (const pt of pts) {
          if (Math.hypot(pt.x - penTapStart.x, pt.y - penTapStart.y) > 6) { isTap = false; break }
        }
      }
      if (isTap) {
        strokeHistory.pop()
        redrawStrokes()
        if (penTapPending.kind === 'obj') {
          const o = objects.find(ob => ob.id === penTapPending.id)
          if (o) {
            for (const ob of objects) ob.selected = false
            selectedIds.value = []
            selectedNoteId.value = null
            o.selected = true
            selectedIds.value.push(o.id)
            if (dctx) { redrawAllDesign(); drawSelectionHighlights(dctx) }
          }
        } else {
          selectNote(penTapPending.id as string)
        }
        scheduleAutoSave()
      }
      penTapPending = null
    }
  }
  if (selecting.value) endSelect()
  // 形状模式：抬起完成
  if (toolMode.value === 'shape' && shapeStart) {
    shapePointerUp({ x: lastX, y: lastY })
  }
}

// 画手势标记（表达层上小标签，标识"这里有个手势"）
function drawGestureMark(gesture: string, x: number, y: number) {
  if (!sctx) return
  const meta = GESTURE_META[gesture]
  if (!meta) return
  sctx.save()
  sctx.font = '11px sans-serif'
  const tw = sctx.measureText(meta.label).width
  sctx.fillStyle = 'rgba(255,255,255,0.9)'
  sctx.strokeStyle = meta.color
  sctx.lineWidth = 1
  // 圆角标签背景
  sctx.beginPath()
  sctx.roundRect(x - 6, y - 16, tw + 12, 18, 4)
  sctx.fill()
  sctx.stroke()
  sctx.fillStyle = meta.color
  sctx.textAlign = 'left'
  sctx.textBaseline = 'middle'
  sctx.fillText(meta.label, x, y - 7)
  sctx.restore()
}

// === 撤销/清空 ===
function undo() {
  if (!sctx || !strokeHistory.length) return
  const popped = strokeHistory.pop()
  // 撤销的是便签最后一笔且组已空 → 清掉残留的便签选中态
  if (popped?.groupId && !strokeHistory.some(s => s.groupId === popped.groupId) && selectedNoteId.value === popped.groupId) {
    clearNoteSelection()
  }
  redrawStrokes()
  sctx.globalAlpha = 1
  checkInk()
  scheduleAutoSave()
}
function clear() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  sctx?.clearRect(0, 0, W, H)
  // 重建 doc
  const fresh = createDocument(doc.value.meta.scene)
  doc.value.layers.splice(0, doc.value.layers.length, ...fresh.layers)
  doc.value.shapes = []
  doc.value.activeLayerId = 0
  layers = doc.value.layers
  activeLayerId = 0
  nextLayerId = fresh.layers.length
  strokeHistory = layers[0].strokes
  if (dctx) { dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H) }
  drawOrigin()
  components.value = []
  gestures.value = []
  hasInk.value = false
  hasDesign.value = false
  selRect.value = null
  lassoPoints = []
  lassoSnapshot = null
  placing.value = null
  shapeStart = null
  shapePoints = []
  shapeSnapshot = null
  eraserPoints = []
  erasing = false
  if (pctx) pctx.clearRect(0, 0, pctx.canvas.width, pctx.canvas.height)
  cuboidPhase.value = 0; cuboidAnchor = null; cuboidFrontTop = null; cuboidFrontLeft = null; cuboidPreviewSnap = null
  cylinderPhase.value = 0; cylinderAnchor.value = null; cylinderRadius.value = 0
  conePhase.value = 0; coneAnchor.value = null; coneRadius.value = 0
}
function clearAllShapes() {
  // 只清除已放置的组件，保留手绘笔迹
  components.value = []
  doc.value.shapes = []
  hasDesign.value = false
  if (dctx) {
    dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H)
    drawOrigin()
  }
  redrawStrokes()
  scheduleAutoSave()
}
function checkInk() {
  if (!sctx) return
  const data = sctx.getImageData(0, 0, sctx.canvas.width, sctx.canvas.height).data
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] > 0) { hasInk.value = true; return }
  }
  hasInk.value = false
}

// 检测是否有内容（橡皮擦后更新 hasInk）
function checkHasInk(): boolean {
  if (!sctx) return false
  const data = sctx.getImageData(0, 0, sctx.canvas.width, sctx.canvas.height).data
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] > 0) return true
  }
  return false
}

// === 保存 / 新增 / 恢复 / 自动缓存 ===
const cacheKey = () => `anvil_sketch_${props.project || 'default'}`
const tabsKey = () => `anvil_sketch_${props.project || 'default'}_tabs`

// 自动保存（静默，始终用时间戳键名）
function autoSaveCurrent() {
  const d = doc.value
  d.activeLayerId = activeLayerId
  d.shapes = components.value.map(c => ({ type: c.type, x: c.x, y: c.y, size: c.size, cylinderRadius: c.cylinderRadius, coneRadius: c.coneRadius, coneTip: c.coneTip, cuboidVectors: c.cuboidVectors, text: c.text, textFont: c.textFont, textColor: c.textColor }))
  d.interpretLog = interpMessages.value.map(m => ({ role: m.role, content: m.content }))
  d.meta.modifiedAt = Date.now()
  const cache = docToCacheV2(d)
  const key = cacheKeyForDoc(d)
  localStorage.setItem(key, JSON.stringify(cache))
  syncTabsMeta()
}

function cacheKeyForDoc(d: SketchDocument) {
  const ts = d.meta.createdAt || Date.now()
  return `${cacheKey()}_${new Date(ts).toISOString().replace(/[:.]/g, '-')}`
}

function syncTabsMeta() {
  const tabMeta = { count: docs.length, activeIndex: docIndex.value, keys: docs.map(d => cacheKeyForDoc(d)) }
  localStorage.setItem(tabsKey(), JSON.stringify(tabMeta))
}

// 自动缓存：防抖 800ms，笔画结束后自动保存
let autoSaveTimer: number | null = null
function scheduleAutoSave() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = window.setTimeout(() => { autoSaveCurrent() }, 800)
}

// 手动保存：弹出命名窗口
const savePromptVisible = ref(false)
const saveName = ref('')
function saveSketch() {
  if (docs.length === 0) return
  saveName.value = doc.value.meta.title || `sketch_${new Date(doc.value.meta.createdAt).toISOString().slice(0, 10)}`
  savePromptVisible.value = true
}
function confirmSave() {
  doc.value.meta.title = saveName.value.trim()
  autoSaveCurrent()
  savePromptVisible.value = false
  errorMsg.value = '💾 已保存：' + saveName.value
  setTimeout(() => { if (errorMsg.value?.startsWith('💾 已保存')) errorMsg.value = '' }, 2000)
}
function cancelSave() { savePromptVisible.value = false }

// 新建标签页（创建即自动保存）
function newSketch() {
  const fresh = createDocument('3d')
  fresh.meta.createdAt = Date.now()
  fresh.meta.modifiedAt = Date.now()
  docs.push(fresh)
  const idx = docs.length - 1
  docIndex.value = idx
  rebindDoc()
  initLayers()
  autoSaveCurrent()
}

function closeTab(idx: number) {
  if (docs.length <= 1) return
  autoSaveCurrent()
  docs.splice(idx, 1)
  if (docIndex.value >= docs.length) docIndex.value = docs.length - 1
  if (idx <= docIndex.value) switchToDoc(docIndex.value)
  else { rebindDoc(); redrawStrokes() }
  syncTabsMeta()
}

// 重绘：从缓存恢复所有 tabs
function restoreSketch() {
  const tabRaw = localStorage.getItem(tabsKey())
  if (!tabRaw) {
    // 无 tabs 元数据 → 尝试旧版单文档恢复
    _restoreSingleLegacy()
    return
  }

  try {
    const tabMeta = JSON.parse(tabRaw)
    if (tabMeta.keys && tabMeta.keys.length) {
      docs.splice(0, docs.length)
      for (const key of tabMeta.keys) {
        const raw = localStorage.getItem(key)
        if (!raw) continue
        const data = JSON.parse(raw)
        const d = createDocument(data.meta?.scene || '3d')
        if (data.layers) {
          d.layers.splice(0, d.layers.length, ...data.layers.map((l: any) => ({
            id: l.id, name: l.name, visible: l.visible ?? true, locked: l.locked ?? false, strokes: l.strokes || [],
          })))
          d.shapes = data.shapes || []
          // 超过2小时的旧文档：清理组件，避免过期数据干扰
          const modifiedAt = data.meta?.modifiedAt || 0
          const TWO_HOURS = 2 * 60 * 60 * 1000
          if (modifiedAt && Date.now() - modifiedAt > TWO_HOURS) {
            d.shapes = []
          }
          d.activeLayerId = data.activeLayerId || 0
          d.meta = data.meta || { scene: '3d', createdAt: Date.now(), modifiedAt: Date.now() }
          d.meta.scene = '3d'
        }
        docs.push(d)
      }
      if (docs.length === 0) docs.push(createDocument('3d'))
      docIndex.value = Math.min(tabMeta.activeIndex || 0, docs.length - 1)
      rebindDoc()
      initLayers()
      // 恢复解读日志
      interpMessages.value = (doc.value.interpretLog || []).map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))
      if (sctx && dctx) {
        dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H)
        drawOrigin()
        redrawStrokes()
        for (const c of components.value) { if (c.cuboidVectors) { drawCuboidFromVectors(dctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec) } else if (c.cylinderRadius) { drawCylinder2D(dctx, c.x, c.y, c.cylinderRadius, c.size || 50) } else if (c.coneRadius && c.coneTip) { if (c.type === 'rcone') { drawRightCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y) } else { drawCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip) } } else if (c.type === 'text') { drawComponent(dctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor) } else { drawComponent(dctx, c.type, c.x, c.y, c.size) } }
      }
      hasInk.value = checkHasInk()
      hasDesign.value = components.value.length > 0
      errorMsg.value = `🔄 已恢复 ${docs.length} 个绘图`
      setTimeout(() => { errorMsg.value = '' }, 1500)
      return
    }
  } catch { /* 回退 */ }

  _restoreSingleLegacy()
}

function _restoreSingleLegacy() {
  // v1 单文档兼容
  const raw = localStorage.getItem(cacheKey())
  if (!raw) { docs.splice(0, docs.length, createDocument('3d')); rebindDoc(); initLayers(); return }
  try {
    const data = JSON.parse(raw)
    if (!data.layers && data.strokes) {
      const v2 = migrateV1toV2(data, '3d')
      docs.splice(0, docs.length, v2)
    } else if (data.layers) {
      const d = createDocument(data.meta?.scene || '3d')
      d.meta.scene = '3d'
      d.layers.splice(0, d.layers.length, ...data.layers.map((l: any) => ({
        id: l.id, name: l.name, visible: l.visible ?? true, locked: l.locked ?? false, strokes: l.strokes || [],
      })))
      d.shapes = data.shapes || (data.components || []).map((c: any) => ({ type: c.type, x: c.x, y: c.y, size: c.size, cylinderRadius: c.cylinderRadius, coneRadius: c.coneRadius, coneTip: c.coneTip, cuboidVectors: c.cuboidVectors, text: c.text, textFont: c.textFont, textColor: c.textColor }))
      // 超过2小时的旧文档：清理组件
      const modifiedAt = data.meta?.modifiedAt || 0
      if (modifiedAt && Date.now() - modifiedAt > 2 * 60 * 60 * 1000) {
        d.shapes = []
      }
      d.activeLayerId = data.activeLayerId || 0
      docs.splice(0, docs.length, d)
    } else {
      docs.splice(0, docs.length, createDocument('3d'))
    }
  } catch { docs.splice(0, docs.length, createDocument('3d')) }
  docIndex.value = 0
  rebindDoc()
  initLayers()
  interpMessages.value = (doc.value.interpretLog || []).map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  if (sctx && dctx) {
    dctx.fillStyle = '#fdfdfd'; dctx.fillRect(0, 0, W, H)
    drawOrigin()
    redrawStrokes()
    for (const c of components.value) { if (c.cuboidVectors) { drawCuboidFromVectors(dctx, {x: c.x, y: c.y}, c.cuboidVectors.frontTop, c.cuboidVectors.frontLeft, c.cuboidVectors.depthVec) } else if (c.cylinderRadius) { drawCylinder2D(dctx, c.x, c.y, c.cylinderRadius, c.size || 50) } else if (c.coneRadius && c.coneTip) { if (c.type === 'rcone') { drawRightCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip.x, c.coneTip.y) } else { drawCone2D(dctx, c.x, c.y, c.coneRadius, c.coneTip) } } else if (c.type === 'text') { drawComponent(dctx, 'text', c.x, c.y, 0, c.text, c.textFont, c.textColor) } else { drawComponent(dctx, c.type, c.x, c.y, c.size) } }
  }
  hasInk.value = checkHasInk()
  hasDesign.value = components.value.length > 0
  scheduleAutoSave()
}

// 挂载时自动恢复
function autoRestore() {
  const tabRaw = localStorage.getItem(tabsKey())
  if (tabRaw) {
    restoreSketch()
    return
  }
  // 旧版单文档
  const raw = localStorage.getItem(cacheKey())
  if (raw) {
    _restoreSingleLegacy()
    return
  }
  initLayers()
}

// === 语音 ===
// 浏览器 Web Speech(免费)优先;不支持/失败 → 录音上传 VoiceService(whisper 免费转写)兜底
// voice 权限(工具授权)控制语音功能可用性
let voiceAllowed = true
;(async () => {
  try {
    const t = await myTools()
    voiceAllowed = t.some(x => x.code === 'voice')
  } catch { /* 默认允许 */ }
})()
let mediaRecorder: any = null
let mediaChunks: Blob[] = []
let mediaStream: any = null

async function toggleVoice() {
  if (!voiceAllowed) {
    errorMsg.value = '你没有语音工具权限,请联系管理员授权'
    return
  }
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (SR && !listening.value) {
    // 浏览器识别优先
    try {
      recognition = new SR()
      recognition.lang = 'zh-CN'
      recognition.continuous = true
      recognition.interimResults = true
      recognition.onresult = (e: any) => {
        let t = ''
        for (let i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript
        voiceText.value = t
      }
      recognition.onerror = (e: any) => {
        if (e.error !== 'aborted' && e.error !== 'no-speech') {
          // 浏览器识别失败 → 录音兜底
          startVoiceFallback()
        }
        listening.value = false
      }
      recognition.onend = () => { listening.value = false }
      recognition.start()
      listening.value = true
      errorMsg.value = ''
      return
    } catch (e: any) {
      // 启动失败 → 录音兜底
    }
  }
  if (listening.value) {
    // 停止浏览器识别
    recognition?.stop()
    listening.value = false
    return
  }
  // 兜底:录音(MediaRecorder)
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop()
    return
  }
  startVoiceFallback()
}

async function startVoiceFallback() {
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      errorMsg.value = '浏览器不支持语音,请用 Chrome/Edge'
      return
    }
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaChunks = []
    const MR = (window as any).MediaRecorder
    if (!MR) { errorMsg.value = '浏览器不支持录音'; mediaStream.getTracks().forEach((t: any) => t.stop()); return }
    mediaRecorder = new MR(mediaStream)
    mediaRecorder.ondataavailable = (e: any) => { if (e.data.size) mediaChunks.push(e.data) }
    mediaRecorder.onstop = async () => {
      mediaStream.getTracks().forEach((t: any) => t.stop())
      const blob = new Blob(mediaChunks, { type: mediaRecorder.mimeType || 'audio/webm' })
      errorMsg.value = '正在识别语音...'
      try {
        const fd = new FormData()
        fd.append('file', blob, 'speech.webm')
        const r = await fetch('/voice-api/recognize', { method: 'POST', body: fd })
        const j = await r.json()
        if (j.text) {
          voiceText.value = j.text
          errorMsg.value = ''
        } else {
          errorMsg.value = '语音识别无结果: ' + (j.error || '')
        }
      } catch (e: any) {
        errorMsg.value = '语音服务不可用: ' + (e?.message || e)
      }
    }
    mediaRecorder.start()
    listening.value = true
    errorMsg.value = '🔴 录音中... 再次点击结束'
  } catch (e: any) {
    errorMsg.value = '语音不可用: ' + (e?.message || e)
  }
}

// === 发送（两层合成） ===
async function gotoDesign() {
  if (sending.value) return
  sending.value = true
  errorMsg.value = ''

  // 没有项目 → 自动创建
  if (!props.project) {
    const name = `sketch_${new Date().toISOString().slice(0, 10)}_${Math.random().toString(36).slice(2, 6)}`
    try { await store.doCreateProject(name); await nextTick() } catch { /* fall through */ }
  }

  // 以解读对话完整记录作为设计输入（含用户更正）
  const sceneDesc = buildSceneDescription()
  let message = ''
  if (interpMessages.value.length) {
    const convo = interpMessages.value
      .map(m => `${m.role === 'user' ? '用户' : 'AI'}: ${m.content}`)
      .join('\n\n')
    message = `【AI 解读对话记录】\n${convo}\n\n---\n${sceneDesc}\n\n注意：坐标已归一化至局部原点，画布X→3D_X，画布Y(翻转)→3D_Z(垂直高度)。尺寸单位=mm。请直接使用三维坐标(X,Y,Z)建模，Y轴深度默认为0。`
  } else {
    message = `${sceneDesc}\n\n注意：坐标已归一化。请分析这张草图并开始设计。`
  }
  sending.value = false
  emit('sent', message)
}

onMounted(() => {
  loadBrushSettings()
  loadCompSettings()
  setupCanvas()
  window.addEventListener('resize', resizeCanvas)
  window.addEventListener('keydown', onKeyDown)
  nextTick(() => {
    autoRestore()
    buildObjects()
  })
})
onBeforeUnmount(() => {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  const hasStrokes = layers.some(l => l.strokes.length > 0)
  if (hasStrokes) autoSaveCurrent()
  window.removeEventListener('resize', resizeCanvas)
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<style scoped>
.sketch-pad.fullscreen {
  position: fixed; inset: 0; z-index: 1000;
  display: flex; flex-direction: column;
  background: #fff; padding: 0; margin: 0;
}
.sketch-pad.embed {
  flex: 1; display: flex; flex-direction: column;
  background: #fff; min-height: 0; position: relative;
}
.sketch-toolbar {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; background: #f8fafc;
  border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; flex-shrink: 0;
}

/* 绘图标签栏 */
.sketch-tabs {
  display: flex; align-items: center; gap: 2px;
  padding: 4px 8px; background: #f1f5f9;
  border-bottom: 1px solid #e2e8f0; overflow-x: auto; flex-shrink: 0;
}
.sketch-tab {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 12px; border-radius: 6px 6px 0 0;
  cursor: pointer; font-size: 12px; color: #556;
  background: #e8ecf0; white-space: nowrap; max-width: 140px;
  border: 1px solid transparent; border-bottom: none;
  transition: all .12s;
}
.sketch-tab:hover { background: #dde2e8; }
.sketch-tab.active { background: #fff; color: #4f46e5; border-color: #e2e8f0; }
.sketch-tab-name { overflow: hidden; text-overflow: ellipsis; }
.sketch-tab-close {
  border: none; background: none; cursor: pointer; font-size: 14px;
  color: #aab; padding: 0; line-height: 1;
}
.sketch-tab-close:hover { color: #dc2626; }
.sketch-tab-add {
  border: none; background: none; cursor: pointer; font-size: 16px;
  color: #889; padding: 2px 8px; flex-shrink: 0;
}
.sketch-tab-add:hover { color: #4f46e5; }
.sk-btn {
  padding: 5px 10px; border: 1px solid #aab; border-radius: 6px;
  background: #fff; cursor: pointer; font-size: 12px; color: #334;
}
.sk-btn:hover { background: #eef2f7; }
.sk-btn:disabled { opacity: .5; cursor: not-allowed; }
.sk-select {
  padding: 5px 8px; border: 1px solid #aab; border-radius: 6px;
  background: #fff; cursor: pointer; font-size: 12px; color: #334;
  outline: none; height: 28px;
}
.sk-select:focus { border-color: #4a7dff; }
.sk-btn.active { background: #e8f0ff; border-color: #4a7dff; color: #4a7dff; }
.sk-btn.recording { background: #fee2e2; border-color: #ef4444; color: #dc2626; }
.sk-primary { background: #4a7dff; border-color: #4a7dff; color: #fff; }
.sk-primary:hover { background: #3a6ce0; }
.sk-spacer { flex: 1; }
.zoom-label { font-size: 11px; color: #888; }
.zoom-slider { width: 90px; accent-color: #4a7dff; margin: 0 2px; cursor: pointer; }
.zoom-val { font-size: 11px; color: #4a7dff; min-width: 38px; text-align: center; }
.palette { display: flex; align-items: center; gap: 4px; padding: 2px 6px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.brush-picker { display: flex; align-items: center; gap: 2px; padding: 2px 4px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.tool-group { display: flex; align-items: center; gap: 2px; padding: 2px 4px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.tool-group .sk-btn { border: 1px solid transparent; }
.tool-group .sk-btn.active { border-color: #4a7dff; }
.shape-picker { display: flex; align-items: center; gap: 2px; padding: 2px 4px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.shape-picker .sk-btn { padding: 4px 8px; font-size: 14px; }
.brush-item { width: 24px; height: 24px; border: none; background: none; cursor: pointer; font-size: 14px; border-radius: 6px; display: flex; align-items: center; justify-content: center; transition: all .12s; }
.brush-item:hover { background: #eef2f7; }
.brush-item.active { background: #e8f0ff; box-shadow: inset 0 0 0 1.5px #4a7dff; }
.width-control { display: flex; align-items: center; gap: 4px; padding: 2px 8px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.width-icon { font-size: 10px; color: #667; }
.width-slider { width: 60px; height: 3px; accent-color: #4a7dff; cursor: pointer; }
.width-val { font-size: 10px; color: #4a7dff; min-width: 34px; text-align: center; }
.pal-item { width: 16px; height: 16px; border-radius: 50%; cursor: pointer; border: 2px solid transparent; transition: all .12s; }
.pal-item:hover { transform: scale(1.15); }
.pal-item.active { border-color: #334; box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px #334; }
.pal-custom { width: 18px; height: 18px; border-radius: 50%; cursor: pointer; border: 2px solid #d1d5db; position: relative; overflow: hidden; transition: all .12s; }
.pal-custom:hover { transform: scale(1.15); }
.pal-custom.active { border-color: #334; box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px #334; }
.pal-color-input { position: absolute; inset: -4px; width: 26px; height: 26px; border: none; padding: 0; cursor: pointer; opacity: 0; }
.pen-label { font-size: 11px; color: #556; min-width: 60px; }

.comp-panel {
  padding: 8px 14px; background: #f0f4ff;
  border-bottom: 1px solid #dbe4ff; flex-shrink: 0;
}
.comp-panel-title { font-size: 11px; color: #4a6da7; margin-bottom: 6px; }
.comp-grid { display: flex; gap: 6px; flex-wrap: wrap; }

/* 位姿编辑面板 */
.pose-panel {
  padding: 6px 14px; background: #f5f8ff;
  border-bottom: 1px solid #d0ddf8; flex-shrink: 0;
}
.pose-panel-title { font-size: 11px; color: #4a6da7; margin-bottom: 4px; }
.pose-grid {
  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
}
.pose-grid label {
  font-size: 11px; color: #667; display: flex; align-items: center; gap: 3px;
}
.pose-grid input {
  border: 1px solid #c7d2fe; border-radius: 4px; padding: 2px 4px; font-size: 11px;
  background: #fff;
}
.pose-grid input:focus { border-color: #4a7dff; outline: none; }

/* 图层面板 */
.layer-panel {
  padding: 0 0; background: #f8fafc;
  border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
}
.layer-panel-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 14px; font-size: 12px; color: #667;
}
.layer-panel-title { color: #8899aa; font-size: 11px; }
.layer-row {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 14px; cursor: pointer; font-size: 12px;
  border-top: 1px solid #f0f0f0; transition: background .1s;
}
.layer-row:hover { background: #f0f4ff; }
.layer-row.active { background: #e8f0ff; }
.layer-eye {
  border: none; background: none; cursor: pointer; font-size: 13px; padding: 0;
  opacity: 0.7; flex-shrink: 0;
}
.layer-eye.off { opacity: 0.2; }
.layer-name {
  flex: 1; color: #334; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  outline: none; padding: 1px 3px; border-radius: 3px;
}
.layer-name[contenteditable="true"]:focus {
  background: #fff; box-shadow: 0 0 0 1px #4a7dff;
}
.layer-count { color: #aab; font-size: 10px; flex-shrink: 0; }
.layer-del {
  border: none; background: none; cursor: pointer; font-size: 14px; color: #cbd5e1;
  padding: 0 2px; flex-shrink: 0;
}
.layer-del:hover { color: #dc2626; }
.comp-item {
  display: flex; align-items: center; gap: 5px; padding: 5px 10px;
  background: #fff; border: 1px solid #c7d2fe; border-radius: 8px;
  cursor: pointer; transition: all .12s;
}
.comp-item:hover { background: #e8f0ff; border-color: #4a7dff; transform: translateY(-1px); }
.comp-item.active { background: #e8f0ff; border-color: #4a7dff; box-shadow: 0 0 0 2px rgba(74,125,255,.25); }
.comp-icon { font-size: 15px; }
.comp-name { font-size: 12px; color: #334; }
.comp-hint {
  padding: 5px 14px; font-size: 12px; color: #7c5cff;
  background: #f5f3ff; border-bottom: 1px solid #e4defa; flex-shrink: 0;
}
.text-settings {
  padding: 4px 14px; font-size: 12px; background: #f5f3ff;
  border-bottom: 1px solid #e4defa; flex-shrink: 0;
  display: flex; gap: 12px; align-items: center;
}
.text-settings label { display: flex; align-items: center; gap: 4px; color: #5b4fc4; }
.text-settings input { border: 1px solid #c7d2fe; border-radius: 4px; padding: 2px 4px; font-size: 11px; }
.sketch-voicetext {
  padding: 5px 14px; font-size: 12px; color: #065f46;
  background: #ecfdf5; border-bottom: 1px solid #a7f3d0; flex-shrink: 0;
}

/* 拖拽提示浮层 */
.drag-tooltip {
  position: absolute; bottom: 60px; left: 16px; z-index: 15;
  pointer-events: none;
  background: rgba(30, 41, 59, 0.88); color: #e2e8f0;
  border-radius: 8px; padding: 8px 12px;
  font-size: 12px; font-family: monospace; line-height: 1.6;
  backdrop-filter: blur(6px);
}
.drag-tt-row { white-space: nowrap; }

.sketch-canvas-wrap {
  position: relative; flex: 1; overflow: hidden; background: #fdfdfd;
}
/* 缩放容器：设计层 + 表达层统一缩放，尺寸由 JS 设置 */
.zoom-layer {
  position: absolute; top: 0; left: 0;
}
/* 设计层（底层） */
.design-layer { position: absolute; top: 0; left: 0; }
.design-canvas { display: block; }
/* 表达层（上层） */
.sketch-canvas {
  position: absolute; top: 0; left: 0;
  display: block; background: transparent; cursor: crosshair;
  touch-action: none;
}
.preview-canvas {
  position: absolute; top: 0; left: 0;
  display: block; background: transparent; pointer-events: none;
  touch-action: none;
}
/* 比例尺 */
.scale-bar {
  position: absolute; bottom: 12px; right: 16px;
  display: flex; flex-direction: column; align-items: flex-end;
  gap: 2px; z-index: 10; pointer-events: none;
}
.scale-bar-line {
  width: 100px; height: 0;
  border-top: 2px solid #1e293b;
  position: relative;
}
.scale-bar-line::before,
.scale-bar-line::after {
  content: ''; position: absolute; top: -4px;
  width: 2px; height: 8px; background: #1e293b;
}
.scale-bar-line::before { left: 0; }
.scale-bar-line::after { right: 0; }
.scale-bar-label {
  font-size: 10px; color: #475569; font-weight: 500;
}
.scale-bar-ratio {
  font-size: 9px; color: #94a3b8;
}
.comp-ghost {
  position: absolute; font-size: 30px; pointer-events: none; z-index: 5;
  transform: translate(-50%, -50%);
  filter: drop-shadow(0 2px 4px rgba(74,125,255,.4));
}
.sel-box {
  position: absolute; border: 1.5px dashed #4a7dff;
  background: rgba(74,125,255,.08); z-index: 4; pointer-events: none;
}
.sketch-hint {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; color: #8899aa;
  font-size: 13px; text-align: center; line-height: 1.9;
  pointer-events: none; background: rgba(255,255,255,.55);
}
.sketch-hint b { color: #4a7dff; }

.comp-list {
  padding: 5px 14px; background: #fafbfc; border-top: 1px solid #e5e5e5;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex-shrink: 0;
}
.comp-list-label { font-size: 11px; color: #888; }
.comp-tag {
  display: inline-flex; align-items: center; gap: 4px; font-size: 11px;
  color: #334; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 6px; padding: 3px 8px;
}
.comp-del { background: none; border: none; color: #999; cursor: pointer; font-size: 12px; }
.comp-del:hover { color: #d33; }
.gesture-tag {
  display: inline-flex; align-items: center; gap: 4px; font-size: 11px;
  background: #fff; border: 1px solid; border-radius: 6px; padding: 3px 8px; font-weight: 500;
}

/* === AI 对话区 === */
.ai-chat {
  border-top: 1px solid #e2e8f0;
  background: #fafbfc;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  max-height: 200px;
}
.ai-chat-history { flex: 1; overflow-y: auto; padding: 8px 14px; min-height: 40px; max-height: 140px; }
.ai-chat-empty { color: #99a; font-size: 12px; text-align: center; padding: 8px 0; }
.ai-msg { display: flex; gap: 6px; margin-bottom: 5px; font-size: 12px; line-height: 1.5; }
.ai-msg.user .ai-msg-text { color: #1a1a1a; background: #e8f0ff; border-radius: 6px; padding: 4px 8px; }
.ai-msg.assistant .ai-msg-text { color: #1a1a1a; background: #f3f4f6; border-radius: 6px; padding: 4px 8px; white-space: pre-wrap; }
.ai-msg-label { font-size: 10px; color: #99a; flex-shrink: 0; padding-top: 4px; }

/* === AI 解读右侧面板 === */
.interp-panel {
  position: absolute; top: 0; right: 0; bottom: 0; z-index: 100;
  width: 360px; background: #fff; border-left: 1px solid #e2e8f0;
  display: flex; flex-direction: column;
  box-shadow: -4px 0 16px rgba(0,0,0,0.06);
}
.interp-panel.collapsed {
  bottom: auto; height: auto; width: auto !important;
}
.interp-panel.collapsed .interp-panel-body,
.interp-panel.collapsed .interp-panel-input { display: none; }
.interp-panel.collapsed .interp-resize-handle { display: none; }
.interp-resize-handle {
  position: absolute; top: 0; bottom: 0; left: 0; width: 6px;
  cursor: col-resize; z-index: 10;
  transition: background .15s;
}
.interp-resize-handle:hover,
.interp-resize-handle:active { background: rgba(74, 125, 255, 0.15); }
.interp-panel-hd {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 14px; border-bottom: 1px solid #e2e8f0; background: #f8fafc;
  flex-shrink: 0;
}
.interp-panel-title { font-size: 13px; font-weight: 600; color: #1e293b; flex: 1; }
.interp-panel-close {
  border: none; background: transparent; font-size: 16px; color: #64748b;
  cursor: pointer; padding: 4px 8px; border-radius: 6px;
}
.interp-panel-close:hover { background: #e2e8f0; color: #1e293b; }
.interp-toggle-btn {
  border: none; background: transparent; font-size: 12px; color: #64748b;
  cursor: pointer; padding: 4px 6px; border-radius: 4px; line-height: 1;
  transition: transform .15s;
}
.interp-toggle-btn:hover { background: #e2e8f0; color: #1e293b; }
.interp-panel-body {
  flex: 1; overflow-y: auto; padding: 12px 14px; min-height: 0;
}
.interp-panel-input {
  display: flex; gap: 6px; padding: 8px 12px; border-top: 1px solid #e2e8f0;
  background: #fafbfc; flex-shrink: 0;
}
.interp-panel-input input {
  flex: 1; padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px;
  font-size: 12px; outline: none;
}
.interp-panel-input input:focus { border-color: #4a7dff; }
.interp-loading {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px 20px; gap: 12px; color: #8892a0; font-size: 13px;
}
.interp-spinner {
  width: 28px; height: 28px;
  border: 3px solid #e5e7eb; border-top-color: #4a7dff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.typing-cursor { color: #4a7dff; animation: blink 0.8s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* === AI 回复弹框(chat) === */
.ai-modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ai-modal-box {
  width: min(560px, 90vw);
  max-height: 70vh;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ai-modal-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}
.ai-modal-title { font-size: 14px; font-weight: 600; color: #1e293b; }
.ai-modal-close {
  border: none;
  background: transparent;
  font-size: 16px;
  color: #64748b;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}
.ai-modal-close:hover { background: #e2e8f0; color: #1e293b; }
.ai-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  min-height: 120px;
}
.ai-chat-input { display: flex; gap: 6px; padding: 6px 14px 10px; }
.ai-chat-input input {
  flex: 1; padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 8px;
  font-size: 13px; outline: none;
}
.ai-chat-input input:focus { border-color: #4a7dff; }

.sketch-error {
  padding: 7px 14px; color: #d33; font-size: 12px;
  background: #fef2f2; border-top: 1px solid #fecaca; flex-shrink: 0;
}

/* 保存命名弹窗 */
.save-overlay {
  position: fixed; inset: 0; z-index: 2000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,.25);
}
.save-dialog {
  background: #fff; border-radius: 10px; padding: 24px 28px;
  width: 340px; box-shadow: 0 8px 32px rgba(0,0,0,.15);
}
.save-dialog-title { font-size: 15px; font-weight: 600; margin-bottom: 14px; }
.save-input {
  width: 100%; padding: 8px 12px; border: 1px solid #d1d5db;
  border-radius: 6px; font-size: 13px; outline: none; box-sizing: border-box;
}
.save-input:focus { border-color: #4a7dff; box-shadow: 0 0 0 2px rgba(74,125,255,.15); }
.save-btns { display: flex; gap: 8px; margin-top: 14px; justify-content: flex-end; }
</style>
