/**
 * SketchDocument — 草图的真实数据结构。
 *
 * 草图是一个多维文件：图层、形状、笔迹、手势、元信息。
 * 平面化（渲染为 PNG）只是它的一个视图。
 *
 * 场景（scene）决定默认图层结构和语义。
 */

// ===== 核心类型 =====

export interface StrokeData {
  color: string
  width: number
  points: { x: number; y: number }[]
  /** 书写模式下所属便签组 id（可选；普通笔迹无此字段，旧缓存兼容） */
  groupId?: string
}

export interface SketchLayer {
  id: number
  name: string
  visible: boolean
  locked: boolean
  strokes: StrokeData[]
}

export interface SketchShape {
  type: string
  x: number
  y: number
  size?: number
  angle?: number
  cylinderRadius?: number
  coneRadius?: number
  coneTip?: {x:number;y:number}
  cuboidVectors?: { frontTop: {x:number;y:number}; frontLeft: {x:number;y:number}; depthVec: {x:number;y:number} }
}

export interface SketchGesture {
  gesture: 'confirm' | 'reject' | 'select' | 'point' | 'erase' | 'emphasize' | 'rotate' | 'move'
  x: number
  y: number
  note: string
}

export type SketchScene = 'mechanical' | 'architectural' | 'art' | 'animation' | '3d'

export interface SketchMeta {
  scene: SketchScene
  title?: string
  author?: string
  createdAt: number
  modifiedAt: number
}

export interface InterpretMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SketchDocument {
  meta: SketchMeta
  layers: SketchLayer[]
  shapes: SketchShape[]
  gestures: SketchGesture[]
  activeLayerId: number
  interpretLog: InterpretMessage[]
}

// ===== 场景配置 =====

export interface SceneConfig {
  id: SketchScene
  label: string
  icon: string
  description: string
  /** 默认图层（按顺序） */
  defaultLayers: { name: string; locked?: boolean }[]
  /** 适用场景说明 */
  useCase: string
}

export const SCENES: Record<SketchScene, SceneConfig> = {
  mechanical: {
    id: 'mechanical',
    label: '机械设计',
    icon: '⚙️',
    description: '零件结构、装配关系、运动示意',
    defaultLayers: [
      { name: '自定义' },
    ],
    useCase: '机械结构概念设计：零件外形、装配方式、传动路线、受力分析草图',
  },
  architectural: {
    id: 'architectural',
    label: '建筑设计',
    icon: '🏛️',
    description: '平面布局、空间关系、立面示意',
    defaultLayers: [
      { name: '墙体轴线' },
      { name: '空间分区' },
      { name: '标注' },
      { name: '家具布置' },
    ],
    useCase: '建筑空间概念设计：功能分区、流线规划、立面草图',
  },
  art: {
    id: 'art',
    label: '绘画',
    icon: '🎨',
    description: '线稿、着色、光影层次',
    defaultLayers: [
      { name: '线稿', locked: true },
      { name: '底色' },
      { name: '阴影' },
      { name: '高光' },
    ],
    useCase: '绘画创作：线稿描边、分层上色、光影叠加',
  },
  animation: {
    id: 'animation',
    label: '动漫',
    icon: '🎬',
    description: '分镜草图、角色设计、场景构图',
    defaultLayers: [
      { name: '背景' },
      { name: '角色' },
      { name: '特效' },
      { name: '注释' },
    ],
    useCase: '动画/漫画分镜：角色造型、场景设定、动作序列草图',
  },
  '3d': {
    id: '3d',
    label: '立体几何',
    icon: '📦',
    description: '立体几何体建模与手绘',
    defaultLayers: [
      { name: '自定义' },
    ],
    useCase: '立体几何体概念设计：长方体、圆柱、球体、圆锥、棱锥等三维形体绘制',
  },
}

// ===== 工厂函数 =====

let _nextDocId = 1

export function createDocument(scene: SketchScene = '3d'): SketchDocument {
  const config = SCENES[scene]
  const now = Date.now()
  const layers: SketchLayer[] = config.defaultLayers.map((l, i) => ({
    id: i,
    name: l.name,
    visible: true,
    locked: l.locked || false,
    strokes: [],
  }))
  return {
    meta: {
      scene,
      createdAt: now,
      modifiedAt: now,
    },
    layers,
    shapes: [],
    gestures: [],
    activeLayerId: 0,
    interpretLog: [],
  }
}

// ===== 缓存序列化 =====

export interface SketchCacheV2 {
  v: 2
  meta: SketchMeta
  layers: SketchLayer[]
  shapes: SketchShape[]
  activeLayerId: number
  interpretLog: InterpretMessage[]
  savedAt: number
}

// v1 兼容：旧数据只有扁平 strokes
export interface SketchCacheV1 {
  v: 1
  strokes: StrokeData[]
  gestures: { gesture: string; x: number; y: number; note: string }[]
  components: { type: string; x: number; y: number }[]
  savedAt: number
}

export function migrateV1toV2(v1: SketchCacheV1, scene: SketchScene = '3d'): SketchDocument {
  const doc = createDocument(scene)
  doc.layers[0].strokes = v1.strokes || []
  doc.shapes = (v1.components || []).map(c => ({ type: c.type, x: c.x, y: c.y }))
  doc.gestures = (v1.gestures || []).map(g => ({
    gesture: g.gesture as SketchGesture['gesture'],
    x: 0, y: 0, note: g.note,
  }))
  doc.meta.modifiedAt = v1.savedAt || Date.now()
  return doc
}

export function docToCacheV2(doc: SketchDocument): SketchCacheV2 {
  return {
    v: 2,
    meta: { ...doc.meta, modifiedAt: Date.now() },
    layers: doc.layers,
    shapes: doc.shapes,
    activeLayerId: doc.activeLayerId,
    interpretLog: doc.interpretLog || [],
    savedAt: Date.now(),
  }
}

// ===== 统一对象模型 =====

/** 画布上的所有可选中、可操作元素统一为此模型 */
export interface DesignObject {
  id: string
  kind: 'stroke' | 'component' | 'text'
  selected: boolean
  /** 包围盒（设计层坐标） */
  bbox: { x: number; y: number; w: number; h: number }
  /** 位姿：位置(x,y,z) + 欧拉角(a,b,c)，单位度 */
  pose: { x: number; y: number; z: number; a: number; b: number; c: number }
  /** 引用源数据 */
  componentIndex?: number   // components.value 下标
  strokeIndex?: number      // strokeHistory 下标（单笔画对象）
  groupId?: string          // 所属组合 id
}

/** 计算笔画包围盒 */
export function strokeBBox(points: { x: number; y: number }[], width: number): { x: number; y: number; w: number; h: number } {
  if (!points.length) return { x: 0, y: 0, w: 0, h: 0 }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const p of points) {
    if (p.x < minX) minX = p.x
    if (p.y < minY) minY = p.y
    if (p.x > maxX) maxX = p.x
    if (p.y > maxY) maxY = p.y
  }
  const pad = width + 4
  return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 }
}

let _objId = 0
export function nextObjectId(): string { return 'obj_' + (++_objId) }
