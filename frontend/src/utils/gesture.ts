/**
 * 手势识别 — 把用户笔迹识别为规范化动作（确认/否定/圈选/指向/擦除/强调/旋转/移动）
 *
 * 原理：对单条笔迹轨迹做几何特征分析（封闭性/折点/方向/长度），
 *       输出 { gesture, position, note }。
 * 识别不了的手势返回 null（作为普通笔迹保留）。
 */

export interface Point {
  x: number
  y: number
}

export interface GestureResult {
  gesture: 'confirm' | 'reject' | 'select' | 'point' | 'erase' | 'emphasize' | 'rotate' | 'move'
  x: number      // 手势中心/起点（画布坐标）
  y: number
  note: string   // 手势的人类可读描述
}

/** 轨迹简化（Douglas-Peucker），保留主要拐点 */
function simplify(points: Point[], tol = 6): Point[] {
  if (points.length <= 2) return points
  // 找离首尾连线最远的点
  let maxD = 0, idx = 0
  const [a, b] = [points[0], points[points.length - 1]]
  for (let i = 1; i < points.length - 1; i++) {
    const d = pointLineDist(points[i], a, b)
    if (d > maxD) { maxD = d; idx = i }
  }
  if (maxD > tol) {
    const left = simplify(points.slice(0, idx + 1), tol)
    const right = simplify(points.slice(idx), tol)
    return [...left.slice(0, -1), ...right]
  }
  return [a, b]
}

function pointLineDist(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x, dy = b.y - a.y
  const len = Math.hypot(dx, dy)
  if (len === 0) return Math.hypot(p.x - a.x, p.y - a.y)
  return Math.abs((p.x - a.x) * dy - (p.y - a.y) * dx) / len
}

/** 两点的夹角变化（度） */
function angleBetween(p1: Point, p2: Point, p3: Point): number {
  const a1 = Math.atan2(p2.y - p1.y, p2.x - p1.x)
  const a2 = Math.atan2(p3.y - p2.y, p3.x - p2.x)
  let d = Math.abs((a2 - a1) * 180 / Math.PI)
  if (d > 180) d = 360 - d
  return d
}

/** 轨迹总长度 */
function pathLength(points: Point[]): number {
  let len = 0
  for (let i = 1; i < points.length; i++) len += Math.hypot(points[i].x - points[i-1].x, points[i].y - points[i-1].y)
  return len
}

/**
 * 识别单条笔迹。
 * @param rawPoints 原始轨迹点（画布坐标）
 * @returns 手势结果或 null（不是手势，是普通笔迹）
 */
export function recognizeGesture(rawPoints: Point[]): GestureResult | null {
  if (rawPoints.length < 8) return null  // 太短不算手势

  const pts = simplify(rawPoints, 8)
  if (pts.length < 2) return null

  const first = pts[0], last = pts[pts.length - 1]
  const len = pathLength(rawPoints)
  const span = Math.hypot(last.x - first.x, last.y - first.y)
  const cx = (first.x + last.x) / 2, cy = (first.y + last.y) / 2

  // 1. 圆圈 ○：起点≈终点，轨迹长 >> 跨度（封闭）
  const closureRatio = span / Math.max(len, 1)
  if (closureRatio < 0.25 && len > 40) {
    return { gesture: 'select', x: cx, y: cy, note: `圈选区域(中心 ${Math.round(cx)},${Math.round(cy)})` }
  }

  // 2. 直线类（跨距大、轨迹接近直线）
  const straightness = span / Math.max(len, 1)
  const isMostlyStraight = straightness > 0.85

  // 箭头 →：一条长直线 + 末端有分叉（简化后首/尾段夹角）
  if (pts.length >= 3 && isMostlyStraight) {
    const seg1 = pts[1], seg2 = pts[pts.length - 2]
    // 检查末尾是否分叉：最后两段方向差大
    const lastAngle = angleBetween(pts[pts.length - 3], pts[pts.length - 2], pts[pts.length - 1])
    if (lastAngle > 25 && lastAngle < 160 && len > 60) {
      return { gesture: 'point', x: first.x, y: first.y, note: `指向(${Math.round(last.x)},${Math.round(last.y)})` }
    }
  }

  // 3. 强调 =：两条近平行的短横线（单笔带折返 → 简化后 3 点、两段平行反向）
  if (pts.length === 3) {
    const a1 = angleBetween(pts[0], pts[1], pts[2])
    const segLen1 = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y)
    const segLen2 = Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y)
    // 折返（夹角大）且两段长度相近 → 可能是 = 或 Z 或 V
    if (a1 > 120 && segLen1 > 20 && segLen2 > 20 && Math.abs(segLen1 - segLen2) / Math.max(segLen1, segLen2) < 0.6) {
      return { gesture: 'emphasize', x: cx, y: cy, note: `强调区域(${Math.round(cx)},${Math.round(cy)})` }
    }
  }

  // 4. 波浪 ~~~~：多次方向变化（折点数多）
  let turns = 0
  for (let i = 1; i < pts.length - 1; i++) {
    const ang = angleBetween(pts[i-1], pts[i], pts[i+1])
    if (ang > 45) turns++
  }
  if (turns >= 3 && len > 50) {
    return { gesture: 'erase', x: cx, y: cy, note: `擦除区域(${Math.round(cx)},${Math.round(cy)})` }
  }

  // 5. 对勾 ✓：两段折线，夹角约 40-120°，起点低终点高（上升趋势）
  if (pts.length === 3) {
    const a1 = angleBetween(pts[0], pts[1], pts[2])
    const segLen1 = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y)
    const segLen2 = Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y)
    const rising = pts[2].y < pts[0].y  // 终点在起点上方（对勾上扬）
    const mid = pts[1]
    // 对勾特征：中点在首尾之间偏下，第二段更长
    if (a1 > 40 && a1 < 140 && segLen2 > segLen1 * 0.7 && mid.y > (pts[0].y + pts[2].y) / 2 && rising) {
      return { gesture: 'confirm', x: cx, y: cy, note: `确认(${Math.round(cx)},${Math.round(cy)})` }
    }
  }

  // 6. 交叉 ✕：轨迹在中点处大角度折返（单笔 X 形状，简化后 3 点夹角 > 100 且两段都长）
  if (pts.length === 3) {
    const a1 = angleBetween(pts[0], pts[1], pts[2])
    const segLen1 = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y)
    const segLen2 = Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y)
    if (a1 > 100 && segLen1 > 25 && segLen2 > 25) {
      return { gesture: 'reject', x: cx, y: cy, note: `否定/删除(${Math.round(cx)},${Math.round(cy)})` }
    }
  }

  return null
}
