"""DraftEngine 几何层:读取模型、提取外形/孔特征、投影轮廓。

依赖成熟内核(FreeCAD OCC),不重复造轮子:
- Part.read:STEP/IGES 等格式解析
- shape.BoundBox:外形尺寸
- face.Surface(Part::GeomCylinder):孔特征(半径/轴线/中心/深度)
- TechDraw.projectToSVG:C++ 数学投影(无 GUI 依赖)
"""

import os
import re
import sys

try:
    import FreeCAD as App
    import Part
    import TechDraw
    HAS_FREECAD = True
except Exception:
    # uvicorn 等进程可能没带 FreeCAD 库路径——自动补
    try:
        for cand in ("/usr/lib/freecad-python3/lib", "/usr/lib/freecad/lib"):
            if os.path.isdir(cand) and cand not in sys.path:
                sys.path.insert(0, cand)
        import FreeCAD as App
        import Part
        import TechDraw
        HAS_FREECAD = True
    except Exception:
        App = Part = TechDraw = None
        HAS_FREECAD = False

# 第一角投影视图定义:(名字, 视线方向, 视图平面轴)
#   Front: 沿 -Y 看(X-Z 平面),Top: 沿 -Z 看(X-Y 平面),Right: 沿 -X 看(Y-Z 平面)
VIEWS = [
    ("Front", (0, -1, 0), ("x", "z")),
    ("Top", (0, 0, -1), ("x", "y")),
    ("Right", (-1, 0, 0), ("y", "z")),
]

SUPPORTED_EXTS = (".step", ".stp", ".iges", ".igs", ".brep")


def load_shape(model_path):
    """读取模型文件 → Part::Shape。支持 STEP/IGES/BREP。"""
    ext = os.path.splitext(model_path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError("不支持的文件格式: %s(支持 %s)" % (ext, SUPPORTED_EXTS))
    return Part.read(model_path)


def analyze_bbox(shape):
    """外形尺寸:返回 dict(L, W, H, xmin, ymin, zmin, xmax, ymax, zmax)。"""
    bb = shape.BoundBox
    return {
        "L": bb.XLength, "W": bb.YLength, "H": bb.ZLength,
        "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
        "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
    }


def analyze_holes(shape):
    """从圆柱面识别孔特征。

    返回 [{radius, axis(0=x,1=y,2=z), center(Vector), depth}]
    - 圆柱面 + 完整圆端面边 = 孔
    - 圆弧面(圆角)排除
    - depth = 圆柱面 bbox 沿轴长度
    """
    holes = []
    seen = set()
    for face in shape.Faces:
        try:
            surf = face.Surface
        except Exception:
            continue
        if surf.TypeId != "Part::GeomCylinder":
            continue
        # 端面必须有完整圆边(孔口)
        has_full_circle = False
        for e in face.Edges:
            try:
                c = e.Curve
            except Exception:
                continue
            if c.TypeId == "Part::GeomCircle":
                has_full_circle = True
                break
        if not has_full_circle:
            continue
        radius = surf.Radius
        axis = surf.Axis
        main = max(range(3), key=lambda i: abs(axis[i]))
        center = surf.Center
        bb = face.BoundBox
        depth = (bb.XLength, bb.YLength, bb.ZLength)[main]
        key = (round(radius, 2), main,
               round(center.x, 1), round(center.y, 1), round(center.z, 1))
        if key in seen:
            continue
        seen.add(key)
        holes.append({"radius": radius, "axis": main, "center": center, "depth": depth})
    return holes


# ---- 面属性分析(特征模式匹配的基础) ----

# 曲面类型 → 工程语义
_FACE_TYPES = {
    "Part::GeomPlane": "plane",
    "Part::GeomCylinder": "cylinder",
    "Part::GeomSphere": "sphere",
    "Part::GeomCone": "cone",
    "Part::GeomToroidal": "torus",
}


def face_type(face):
    """面的曲面类型:plane/cylinder/sphere/cone/torus/unknown。"""
    try:
        return _FACE_TYPES.get(face.Surface.TypeId, "unknown")
    except Exception:
        return "unknown"


def face_attrs(face):
    """提取面的完整属性(模式匹配用)。

    返回 dict:type/area/center/normal/radius/axis/axis_main/_face_bb
    圆柱面额外:radius/axis/axis_main
    平面额外:normal
    """
    t = face_type(face)
    bb = face.BoundBox
    attrs = {
        "type": t,
        "area": face.Area,
        "center": face.CenterOfMass,
        "normal": None,
        "radius": None,
        "axis": None,
        "axis_main": None,
        "_face_bb": (bb.XLength, bb.YLength, bb.ZLength),
    }
    try:
        surf = face.Surface
        if t == "plane":
            n = face.normalAt(0, 0)
            attrs["normal"] = n
        elif t == "cylinder":
            attrs["radius"] = surf.Radius
            ax = surf.Axis
            attrs["axis"] = ax
            attrs["axis_main"] = max(range(3), key=lambda i: abs(ax[i]))
        elif t == "sphere":
            attrs["radius"] = surf.Radius
            attrs["surf_center"] = surf.Center  # 真实球心(face.CenterOfMass 是面质心)
    except Exception:
        pass
    return attrs


def all_face_attrs(shape):
    """所有面的属性列表(缓存,一次遍历)。"""
    return [face_attrs(f) for f in shape.Faces]


def main_axis_of(vec):
    """向量主轴方向:0=x, 1=y, 2=z。"""
    return max(range(3), key=lambda i: abs(vec[i]))


def axis_dist2(v1, v2, axis_main):
    """两个向量沿指定主轴方向的垂直距离平方(用于同轴判断)。"""
    dx, dy, dz = v1.x - v2.x, v1.y - v2.y, v1.z - v2.z
    d = [0.0, 0.0, 0.0]
    d[axis_main] = 1.0
    dot = dx * d[0] + dy * d[1] + dz * d[2]
    return dx * dx + dy * dy + dz * dz - dot * dot


def project_views(shape):
    """三方向轮廓投影。返回 {name: svg_fragment}。"""
    frags = {}
    for name, vec, _ in VIEWS:
        frags[name] = TechDraw.projectToSVG(shape, App.Vector(*vec))
    return frags


# ---- FreeCAD HLR 投影(TechDraw 内核,勿自行重造) ----

# 第一角三视图方向。投影结果的 (u,v) 姿态随模型而定(原点/正负号不固定),
# 故映射必须用实际投影包围盒归一化,不能写死公式。
HLR_VIEWS = {
    "Front": (0, -1, 0),
    "Top": (0, 0, -1),
    "Left": (1, 0, 0),
}


def project_hlr(shape, view_name):
    """FreeCAD TechDraw HLR 投影:可见/隐藏边分离。

    返回 (visible, hidden): 各为 [Part.Edge]。
    projectEx 返回 8 组:V/V1/VN/VI(可见) + H/H1/HN/HI(隐藏)。
    """
    r = TechDraw.projectEx(shape, App.Vector(*HLR_VIEWS[view_name]))
    visible = [e for comp in r[:4] for e in comp.Edges]
    hidden = [e for comp in r[4:] for e in comp.Edges]
    return visible, hidden


def view_mapping(edges, target_w, target_h, swap=False, flip_x=False, flip_y=False):
    """按投影实际包围盒映射到 (0..target_w, 0..target_h)。

    两个关键点(空心球 bug 修复):
    1. 包围盒用 OCC 精确边 BoundBox——采样离散(Number=8)会错过圆弧
       顶点(如半圆弧的 90° 极值点),包围盒偏小导致图形放大溢出视图框;
    2. 等比缩放 + 居中(su/sv 取同一比例)——独立拉伸会把圆压成椭圆
       ("歪圆"),GB 视图禁止失真。
    swap: 投影 u/v 与图纸 x/y 交换(u→y, v→x)。
    flip: 各自镜像。所有参数由 auto_transform 运行时测定,调用方不写死。
    返回 map_fn(p) -> (px, py)(0 起,未含平移与缩放)。
    """
    u0 = v0 = float("inf")
    u1 = v1 = float("-inf")
    for e in edges:
        got = False
        try:
            bb = e.BoundBox
            u0 = min(u0, bb.XMin); u1 = max(u1, bb.XMax)
            v0 = min(v0, bb.YMin); v1 = max(v1, bb.YMax)
            got = True
        except Exception:
            pass
        if not got:
            try:
                for p in e.discretize(Number=32):
                    u0 = min(u0, p.x); u1 = max(u1, p.x)
                    v0 = min(v0, p.y); v1 = max(v1, p.y)
            except Exception:
                continue
    if u0 > u1 or v0 > v1:
        u0, u1, v0, v1 = 0.0, 1.0, 0.0, 1.0
    su = (u1 - u0) or 1.0
    sv = (v1 - v0) or 1.0
    # 等比:swap 时 u→页y、v→页x,先换算页向宽高再取小比例
    w_src, h_src = (sv, su) if swap else (su, sv)
    s = min(target_w / w_src, target_h / h_src)
    ox = (target_w - w_src * s) / 2.0
    oy = (target_h - h_src * s) / 2.0

    def map_fn(p):
        fu = (p.x - u0) * s
        fv = (p.y - v0) * s
        if swap:
            x, y = fv + ox, fu + oy
        else:
            x, y = fu + ox, fv + oy
        if flip_x:
            x = target_w - x
        if flip_y:
            y = target_h - y
        return x, y
    return map_fn


# 第一角视图语义:图纸 x+ / y↓(向下) 对应的模型方向(3 维单位向量)
#   Front: x+→+X(长), y↓→-Z(高,下=模型低处)
#   Top:   x+→+X(长), y↓→-Y(前,下=模型前方;后缘贴主视图)
#   Left:  x+→+Y(宽,右=模型后方), y↓→-Z(高,下=模型低处)
FIRST_ANGLE_SEMANTICS = {
    "Front": ((1, 0, 0), (0, 0, -1)),
    "Top":   ((1, 0, 0), (0, -1, 0)),
    "Left":  ((0, 1, 0), (0, 0, -1)),
}


def page_pos(view_name, bbox, x, y, z, vw_mm, vh_mm):
    """模型坐标 → 视图框内图纸坐标(0..vw, 0..vh),与投影映射语义一致。

    标注定位用此函数,与 HLR 视图朝向由同一语义表保证一致。
    """
    sx, sy = FIRST_ANGLE_SEMANTICS[view_name]
    lo = (bbox["xmin"], bbox["ymin"], bbox["zmin"])
    hi = (bbox["xmax"], bbox["ymax"], bbox["zmax"])
    pos = (x, y, z)

    def _frac(vec):
        main = max(range(3), key=lambda k: abs(vec[k]))
        sign = 1 if vec[main] > 0 else -1
        span = (hi[main] - lo[main]) or 1.0
        f = (pos[main] - lo[main]) / span
        return f if sign > 0 else 1.0 - f

    return _frac(sx) * vw_mm, _frac(sy) * vh_mm


def auto_transform(view_name, bbox):
    """三轴探针运行时测定投影变换 → (swap, flip_x, flip_y)。

    原理:分别在模型 x/y/z 正方向放小盒投影,与原点小盒比中心,
    得每根模型轴在投影 (u,v) 的位移;再按第一角语义判定:
    - 语义 x 轴落在 v 上 → 需转置(swap:u/v 互换)
    - 方向与语义相反 → flip
    任何模型、任何投影姿态自适应,不写死常数。
    """
    direction = HLR_VIEWS[view_name]
    sx, sy = FIRST_ANGLE_SEMANTICS[view_name]

    def _center(sh):
        r = TechDraw.projectEx(sh, App.Vector(*direction))
        es = [e for c in r[:4] for e in c.Edges]
        xs, ys = [], []
        for e in es:
            for p in e.discretize(Number=4):
                xs.append(p.x); ys.append(p.y)
        if not xs:
            return None
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    origin = Part.makeBox(1, 1, 1)
    c0 = _center(origin)
    if not c0:
        return False, False, False
    axes = {}
    for i, off in enumerate(((bbox["L"], 0, 0), (0, bbox["W"], 0), (0, 0, bbox["H"]))):
        c1 = _center(Part.makeBox(1, 1, 1, App.Vector(*off)))
        if c1:
            axes[i] = (c1[0] - c0[0], c1[1] - c0[1])

    def _dominant(vec3):
        main = max(range(3), key=lambda k: abs(vec3[k]))
        return main, (1 if vec3[main] > 0 else -1)

    sx_ax, sx_sign = _dominant(sx)
    sy_ax, sy_sign = _dominant(sy)

    def _axis_dir(ax, on_u):
        """模型轴 ax 在 u(True)/v(False) 上的符号;探针缺失返回 0。"""
        if ax not in axes:
            return 0
        du, dv = axes[ax]
        return du if on_u else dv

    # 语义 x 轴应沿图纸 x(投影 u)。若它实际主要在 v 上 → 转置
    if sx_ax in axes:
        du, dv = axes[sx_ax]
        swap = abs(dv) > abs(du)
    else:
        swap = False
    # 转置后图纸 x 由 v 承载(not swap=False → u 承载)
    # 图纸 x+ ∝ 语义x方向:承载坐标随 sx_ax 增大的符号须与 sx_sign 一致,否则 flip_x
    s_x = _axis_dir(sx_ax, not swap)
    flip_x = (s_x != 0) and not ((s_x > 0) == (sx_sign > 0))
    # 图纸 y+(向下) ∝ 语义y方向:承载坐标随 sy_ax 增大的符号须与 sy_sign 一致,否则 flip_y
    s_y = _axis_dir(sy_ax, swap)
    flip_y = (s_y != 0) and not ((s_y > 0) == (sy_sign > 0))
    return swap, flip_x, flip_y


def project_edges(shape, map_fn, npts=24):
    """已废弃:被 project_hlr + view_mapping 取代。"""
    raise NotImplementedError


def svg_bbox(frag):
    """解析投影 SVG 片段的坐标范围(模型 mm)。"""
    xs, ys = [], []
    for m in re.finditer(r"[ML]\s*(-?\d+\.?\d*)\s*,?\s*(-?\d+\.?\d*)", frag):
        xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    for m in re.finditer(r'cx="(-?\d+\.?\d*)" cy="(-?\d+\.?\d*)" r="(-?\d+\.?\d*)"', frag):
        r = float(m.group(3))
        xs += [float(m.group(1)) - r, float(m.group(1)) + r]
        ys += [float(m.group(2)) - r, float(m.group(2)) + r]
    if not xs or not ys:
        return (0, 1, 0, 1)
    return (min(xs), max(xs), min(ys), max(ys))
