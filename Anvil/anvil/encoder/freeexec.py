"""dltQ 数字矩阵 → FreeCAD 代码编译器（收报机真执行层）

重放编译：账本全部指令（含当前）逐条编译为 Part API 代码，
交 FreeCADTool（优先 CADService 8102，降级本地 FreeCAD）执行，
产物 STL 落项目 cad/ 目录，前端 viewer 直接可见。

约定对齐 codetable.py：
- 体中心 = 位置锚点（756 定位于[x,y,z] 即体中心坐标）
- 757 朝向[倾角,转角]（度）：先绕全局 X 倾角，再绕全局 Z 转角
- 750 下方贴合 / 751 上方定位 / 752 XY中心对齐：BoundBox 动态表达式，内核算坐标
- 207 打孔：Z 向贯穿通孔（深度省略语义），目标=引用对象
- 布尔 100/101/102：操作数=紧随引用（992=次新 991=最新 990,n=跨指令），
  缺省 基体=次新 刀具=最新（`101` 即 次新−最新）

支持范围：体元 1~5/7/8（6 楔形待接入）、布尔 100/101/102、打孔 207、
变换 300/301/302、定位 750/751/752/756/757、引用 990/991/992。
其余算子（材质/约束/IO/阵列等）回显有效，执行时跳过并注释标注。
"""
import math
import os

from anvil.encoder.codetable import get, CODETABLE

# 算子码全集(段断判定:数值撞码=下一段算子,不是参数)
_OPSET = set(CODETABLE.keys())

from anvil.encoder.codetable import geo_arity, GEOMETRY_SCHEMA

# 体元编号 → FreeCAD 构造（size 按表顺序;位置/方位由调用方应用）
def _emit_body(code, vals, var, lines):
    if code == 1:
        lines.append("%s = Part.makeBox(%g, %g, %g)" % (var, vals[0], vals[1], vals[2]))
    elif code == 2:
        lines.append("%s = Part.makeCylinder(%g, %g)" % (var, vals[0], vals[1]))
    elif code == 3:
        # OCC 防御:等半径圆锥(makeCone r1==r2)抛 OCCDomainError → 退化为圆柱
        if abs(vals[0] - vals[1]) < 1e-9:
            lines.append("%s = Part.makeCylinder(%g, %g)" % (var, vals[0], vals[2]))
        else:
            lines.append("%s = Part.makeCone(%g, %g, %g)" % (var, vals[0], vals[1], vals[2]))
    elif code == 4:
        lines.append("%s = Part.makeSphere(%g)" % (var, vals[0]))
    elif code == 5:
        lines.append("%s = Part.makeTorus(%g, %g)" % (var, vals[0], vals[1]))
    elif code == 7:  # 椭球 = 球缩放
        lines.append("_m = FreeCAD.Matrix(%g, 0, 0, 0, 0, %g, 0, 0, 0, 0, %g, 0)" % tuple(vals[:3]))
        lines.append("%s = Part.makeSphere(1.0).transformGeometry(_m)" % var)
    elif code == 8:  # 正棱柱 = 外接圆多边形拉伸
        lines.append("_pts = [Vector(%g * math.cos(2 * math.pi * i / %d), "
                     "%g * math.sin(2 * math.pi * i / %d), 0) for i in range(%d)]"
                     % (vals[1], int(vals[0]), vals[1], int(vals[0]), int(vals[0])))
        lines.append("_w = Part.makePolygon(_pts + [_pts[0]])")
        lines.append("%s = _w.extrude(Vector(0, 0, %g))" % (var, vals[2]))
    else:
        return False
    return True


def _read_refs(d, i, stack, seq):
    """从 i 起收集紧邻引用算子 → [((var, order), kind, num)]；order=创建序键(seq,k)"""
    refs = []
    n = len(d)
    while i < n:
        c = int(d[i])
        if c == 990 and i + 1 < n:
            num = int(d[i + 1])
            refs.append((num, 1, "990", num))
            i += 2
        elif c == 991:
            refs.append((seq, len(stack), "991", None))
            i += 1
        elif c == 992:
            refs.append((seq, max(len(stack) - 1, 0), "992", None))
            i += 1
        else:
            break
    return refs, i


def compile_all(entries, out_dir):
    """编译账本全部指令（按序重放）→ FreeCAD 代码文本。

    entries: [(seq, dltq_list)]，最后一条为当前指令。
    out_dir: 产物目录（绝对路径），装配 STL 落 out_dir/assembly.stl。
    返回 (code_lines, meta)  meta: {seq: result_var, skipped: [(code, term)]}
    """
    lines = ["import Part, math, FreeCAD", "from FreeCAD import Vector", "import Mesh"]
    result_var = {}      # seq -> 结果变量名
    all_result_vars = [] # 装配清单（每条指令的最终结果）
    skipped = []

    for seq, d in entries:
        stack = []       # 本指令对象栈（991=最新 992=次新）
        vn = [0]
        res = [None]
        new_vars = []    # 本指令新建体元变量（干涉检查对象）
        fuse_seen = [False]  # 本指令含融合算子 100（融合语义下重叠合法）

        def newvar():
            vn[0] += 1
            return "s%d_%d" % (seq, vn[0])

        def resolve(kind, num):
            """→ (变量名, 创建序键)；创建序用于布尔操作数排序（先建=基体）"""
            if kind == "990":
                if num in result_var:
                    return result_var[num], (num, 1)
                return (("s%d_1" % num), (num, 1)) if num != seq else (None, None)
            if kind == "991":
                return (stack[-1] if stack else res[0]), (seq, len(stack))
            return (stack[-2] if len(stack) >= 2 else (stack[-1] if stack else res[0])), (seq, max(len(stack) - 1, 0))

        lines.append("# ===== 指令 #%d =====" % seq)
        i, n = 0, len(d)
        while i < n:
            c = int(d[i]); i += 1
            entry = get(c)

            if c in (990, 991, 992) or entry is None:
                continue  # 游离引用/非法码：跳过（引用通常已被消费）

            term = entry["term"]

            # --- 体元 1~8（参数表 v2：尺寸+位置[体心]+方位,严格定长）---
            if 1 <= c <= 99:
                g = GEOMETRY_SCHEMA.get(c)
                n_full = geo_arity(c)
                if not g or not n_full:
                    lines.append("# 体元 %d 未定义,跳过" % c)
                    i += 1
                    continue
                # 严格定长吞全参数(尾部不足补 0——协议要求 LLM 写满,违规在回显暴露)
                vals = [(float(d[i + k]) if i + k < n else 0.0) for k in range(n_full)]
                i += n_full
                # -1 未定残留防御:求解器漏网(无约束算子)——显式失败而非臆造落位
                if any(v == -1 for v in vals):
                    lines.append("raise RuntimeError('SOLVE: 体元%d 位置含未定参数(-1)——"
                                 "无约束算子可推导,应先欠约束提问')" % c)
                    skipped.append((c, term + "(含-1未解)"))
                    continue
                if c == 6:
                    lines.append("# 楔形(待接入执行) 跳过")
                    skipped.append((c, term))
                    continue
                ns = len(g["size"])
                size = vals[:ns]
                pos = vals[ns:ns + 3]
                orient = vals[ns + 3:ns + 5] if not g.get("no_orient") else []
                var = newvar()
                _emit_body(c, size, var, lines)
                # 位置=体心绝对坐标(严格平移;2026-09-07 取消"全0不平移"特判——
                # 特判下体心(0,0,0)留默认原点角,LLM 对两种语义摇摆,后续推算全错位)
                lines.append("%s.translate(Vector(%g, %g, %g) - %s.BoundBox.Center)  # 体心(%g,%g,%g)"
                             % (var, pos[0], pos[1], pos[2], var, pos[0], pos[1], pos[2]))
                # 地面约束:零件不埋入地下——ZMin<0 整体抬升至贴地(机械常识,显式化)
                lines.append("if %s.BoundBox.ZMin < -1e-9: %s.translate(Vector(0, 0, -%s.BoundBox.ZMin))  # 落地"
                             % (var, var, var))
                # 方位=倾角/转角(绕自身中心旋转)
                if orient and any(abs(o) > 1e-9 for o in orient):
                    lines.append("_c = %s.BoundBox.Center" % var)
                    if abs(orient[0]) > 1e-9:
                        lines.append("%s.rotate(_c, Vector(1, 0, 0), %g)" % (var, orient[0]))
                    if abs(orient[1]) > 1e-9:
                        lines.append("%s.rotate(_c, Vector(0, 0, 1), %g)" % (var, orient[1]))
                stack.append(var)
                new_vars.append(var)
                res[0] = var
                continue

            # --- 布尔 100/101/102 ---
            if c in (100, 101, 102):
                if c == 100:
                    fuse_seen[0] = True
                refs, i = _read_refs(d, i, stack, seq)
                if len(refs) >= 2:
                    # 创建序排序：先建=基体，后建=刀具（挖洞=后建的体是工具）
                    refs.sort(key=lambda r: (r[0], r[1]))
                    base, _o = resolve(refs[0][2], refs[0][3])
                    tool, _o = resolve(refs[-1][2], refs[-1][3])
                elif len(refs) == 1:
                    base, _o = resolve(*refs[0][2:])
                    tool = stack[-1] if stack else res[0]
                else:
                    base = stack[-2] if len(stack) >= 2 else None
                    tool = stack[-1] if stack else None
                if not base or not tool:
                    lines.append("# %s: 操作数不足，跳过" % term)
                    continue
                op = {100: "fuse", 101: "cut", 102: "common"}[c]
                lines.append("_v0 = %s.Volume" % base)
                lines.append("%s = %s.%s(%s)  # %s" % (base, base, op, tool, term))
                # 几何 sanity:布尔必须按方向改变体积,否则操作数不相交/悬空——
                # 静默错误(账对文件对几何错)显式化,弱模型/编译器缺陷都拦在这
                if c == 101:
                    lines.append("if not (%s.Volume < _v0 - 1e-6): raise RuntimeError('SANITY: 减(%s)未切到材料——刀具与基体不相交')" % (base, term))
                elif c == 100:
                    lines.append("if not (%s.Volume > _v0 + 1e-6): raise RuntimeError('SANITY: 并(%s)未增加体积——操作数完全重合?')" % (base, term))
                else:
                    lines.append("if %s.Volume <= 1e-9: raise RuntimeError('SANITY: 交(%s)为空——操作数不相交')" % (base, term))
                res[0] = base
                continue

            # --- 207 打孔：定长段 [目标引用..., 半径, (深度), (756,x,y,z)] ---
            # 一段矩阵可写多个 207 段(重复特征=重复段,2026-09-06 用户定);
            # 每段至多一个 756 孔心定位(z 忽略——贯穿由目标 bbox 决定),
            # 无 756 则打目标中心孔(兼容旧语义)。遇下一个段算子即断段。
            if c == 207:
                refs, i = _read_refs(d, i, stack, seq)
                target = resolve(refs[0][2], refs[0][3])[0] if refs else (res[0] or (stack[-1] if stack else None))
                r, has_r = None, False
                depth = None
                hole_xy = None
                drill_from_top = True   # 贯穿孔默认从顶面往下打
                while i < n:
                    c2 = int(d[i])
                    # 段内算子:仅引用与孔位/方向修饰;其余(207/体元/布尔/755...)
                    # 一律断段交外层——数值参数按位吞(先半径后深度),吞满即断
                    if c2 == 990 and i + 1 < n:
                        if target is None:
                            target = resolve("990", int(d[i + 1]))[0]
                        i += 2
                    elif c2 in (991, 992):
                        i += 1
                    elif c2 == 756 and i + 3 < n:
                        hole_xy = (float(d[i + 1]), float(d[i + 2]))
                        i += 4  # 756,x,y,z(z 忽略)
                    elif c2 == 751:
                        drill_from_top = True
                        i += 1
                    elif c2 == 750:
                        drill_from_top = False
                        i += 1
                    elif c2 == 752:
                        i += 1  # 中心对齐=无 756 的缺省
                    elif not has_r and 0 < float(d[i]) < 10000:
                        r, has_r = float(d[i]), True  # 引用后首个数值=半径(位置优先,码值不歧义)
                        i += 1
                    elif depth is None and 0 < float(d[i]) < 10000 and int(d[i]) not in _OPSET:
                        depth = float(d[i])  # 盲孔深度(可选;值不得撞算子码——撞码=下一段)
                        i += 1
                    else:
                        break  # 断段:下一段算子/吞满后的多余 token → 交外层
                if not has_r:
                    r = 10.0
                if not target:
                    lines.append("# 打孔: 目标缺失，跳过")
                    continue
                # 孔位:756 给定 → (x,y);否则目标 bbox 中心
                lines.append("_bb = %s.BoundBox" % target)
                if hole_xy:
                    lines.append("_hx, _hy = %g, %g" % hole_xy)
                else:
                    lines.append("_hx, _hy = _bb.Center.x, _bb.Center.y")
                if depth:
                    # 盲孔:从顶面往下 depth(起点=顶面,方向 -Z)
                    lines.append("_tool = Part.makeCylinder(%g, %g, Vector(_hx, _hy, _bb.ZMax), Vector(0,0,-1))" % (r, depth))
                else:
                    # 贯穿:刀具覆盖目标 Z 全厚 +1 余量
                    lines.append("_zthick = _bb.ZMax - _bb.ZMin")
                    lines.append("_tool_h = _zthick + 1.0")
                    if drill_from_top:
                        # 从顶面往下:起点=ZMax,方向 -Z(起点若用 ZMax-tool_h 会整段落在板外,切空)
                        lines.append("_tool = Part.makeCylinder(%g, _tool_h, Vector(_hx, _hy, _bb.ZMax), Vector(0,0,-1))" % r)
                    else:
                        lines.append("_tool = Part.makeCylinder(%g, _tool_h, Vector(_hx, _hy, _bb.ZMin - 1.0), Vector(0,0,1))" % r)
                lines.append("_v0 = %s.Volume" % target)
                lines.append("%s = %s.cut(_tool)  # 打孔 r=%g @(%g,%g) %s"
                             % (target, target, r, hole_xy[0] if hole_xy else 0, hole_xy[1] if hole_xy else 0,
                                "深%g" % depth if depth else "贯穿"))
                # 几何 sanity:打孔必须减少体积——刀具悬空(孔心在目标外/起点错)显式报警
                lines.append("if not (%s.Volume < _v0 - 1e-6): raise RuntimeError('SANITY: 打孔 r=%g @(%g,%g) 未切到材料——孔心在目标外?')"
                             % (target, r, hole_xy[0] if hole_xy else 0, hole_xy[1] if hole_xy else 0))
                res[0] = target
                continue

            # --- 756 定位于（体中心）---
            if c == 756:
                if res[0] and i + 2 < n:
                    x, y, z = float(d[i]), float(d[i + 1]), float(d[i + 2])
                    i += 3
                    lines.append("%s.translate(Vector(%g, %g, %g) - %s.BoundBox.Center)  # 定位于体中心"
                                 % (res[0], x, y, z, res[0]))
                continue

            # --- 757 朝向[倾角,转角]（度）---
            if c == 757:
                if res[0]:
                    tilt = float(d[i]) if i < n else 0.0
                    azim = float(d[i + 1]) if i + 1 < n else 0.0
                    i += 2
                    if tilt or azim:
                        lines.append("_c = %s.BoundBox.Center" % res[0])
                        if tilt:
                            lines.append("%s.rotate(_c, Vector(1, 0, 0), %g)" % (res[0], tilt))
                        if azim:
                            lines.append("%s.rotate(_c, Vector(0, 0, 1), %g)" % (res[0], azim))
                continue

            # --- 750/751/752 相对定位 ---
            if c in (750, 751, 752):
                if not res[0]:
                    continue
                # 引用操作数
                if i < n and int(d[i]) == 990 and i + 1 < n:
                    refv = result_var.get(int(d[i + 1])) or ("s%d_1" % int(d[i + 1]))
                    i += 2
                else:
                    refv = None  # 缺省=引用上一条结果
                if not refv and len(all_result_vars) >= 1:
                    refv = all_result_vars[-1]
                if not refv:
                    continue
                if c == 750:  # 下方贴合：当前顶面贴引用底面
                    lines.append("%s.translate(Vector(0, 0, %s.BoundBox.ZMin - %s.BoundBox.ZMax))"
                                 % (res[0], refv, res[0]))
                elif c == 751:  # 上方：当前底面贴引用顶面
                    lines.append("%s.translate(Vector(0, 0, %s.BoundBox.ZMax - %s.BoundBox.ZMin))"
                                 % (res[0], refv, res[0]))
                else:  # 752 XY 中心对齐（z 分量不动，避免覆盖 750/751 贴合结果）
                    lines.append("%s.translate(Vector(%s.BoundBox.Center.x - %s.BoundBox.Center.x, %s.BoundBox.Center.y - %s.BoundBox.Center.y, 0))"
                                 % (res[0], refv, res[0], refv, res[0]))
                continue

            # --- 300/301/302 变换 ---
            if c == 300:
                dx, dy, dz = float(d[i]), float(d[i + 1]), float(d[i + 2]); i += 3
                if res[0]:
                    lines.append("%s.translate(Vector(%g, %g, %g))" % (res[0], dx, dy, dz))
                continue
            if c == 301:
                axis, ang = int(d[i]), float(d[i + 1]); i += 2
                if res[0]:
                    ax = {1: "Vector(1,0,0)", 2: "Vector(0,1,0)", 3: "Vector(0,0,1)"}[axis]
                    lines.append("%s.rotate(%s.BoundBox.Center, %s, %g)" % (res[0], res[0], ax, ang))
                continue
            if c == 302:
                s = float(d[i]); i += 1
                if res[0]:
                    lines.append("_m = FreeCAD.Matrix(%g, 0, 0, 0, 0, %g, 0, 0, 0, 0, %g, 0)" % (s, s, s))
                    lines.append("%s = %s.transformGeometry(_m)" % (res[0], res[0]))
                continue

            # --- 其余算子：回显有效，执行跳过 ---
            # 关键:按译码表 params 定长吞参——不吞的话后续数字会被误析为
            # 体元参数(如 755 后的 1,-30,-30 → makeBox(-30,-30,0) 负尺寸崩,
            # 且账本被污染后每轮重放都崩,污染扩散)
            _spec = entry.get("params") or []
            _j = 0
            while _j < len(_spec) and i < n:
                _pn = _spec[_j]
                if any(_k in _pn for _k in ("引用", "对象", "目标", "面", "轴", "轮廓", "方向")):
                    i += 2 if int(d[i]) == 990 else 1
                else:
                    i += 1
                _j += 1
            lines.append("# %d %s: 回显有效，执行暂跳过" % (c, term))
            skipped.append((c, term))

        # --- 干涉检查(装配语义,2026-09-07 用户定)-------------------------
        # 独立放置的新体元不得与既有装配体/本轮其他新体重叠(体积相交>0);
        # 融合语义(本指令含 100)重叠合法,跳过。报错带双方 bbox——喂回 LLM
        # 重译时能推算正确位置(模糊位置"旁边"=贴既有边+10mm间隙)。
        if new_vars and not fuse_seen[0] and all_result_vars:
            for _k, _nv in enumerate(new_vars):
                _others = list(all_result_vars) + new_vars[:_k]
                _oth = "_oth_%d_%d" % (seq, _k)
                lines.append("%s = Part.makeCompound([%s])" % (_oth, ", ".join(_others)))
                lines.append("_iv = %s.common(%s).Volume" % (_nv, _oth))
                lines.append("if _iv > 1e-6:")
                lines.append("    _b1, _b2 = %s.BoundBox, %s.BoundBox" % (_nv, _oth))
                lines.append("    raise RuntimeError("
                             "'INTERFERE: 新建体元与已有对象重叠 %.1f mm3(独立放置不得干涉)。"
                             "新体 bbox=x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f];"
                             "已有装配 bbox=x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f]。"
                             "修正:采用建议体心(%.1f,%.1f,%.1f)(沿X+贴边10mm间隙,"
                             "y/z保持现值;也可换Y向:体心y=%.1f);"
                             "要连成一体则矩阵体元后追加融合算子 100,990,目标序号'"
                             " % (_iv, _b1.XMin, _b1.XMax, _b1.YMin, _b1.YMax, _b1.ZMin, _b1.ZMax,"
                             " _b2.XMin, _b2.XMax, _b2.YMin, _b2.YMax, _b2.ZMin, _b2.ZMax,"
                             " _b2.XMax + _b1.XLength / 2 + 10, _b1.YMin + _b1.YLength / 2,"
                             " _b1.ZMin + _b1.ZLength / 2, _b2.YMax + _b1.YLength / 2 + 10))")

        if res[0]:
            result_var[seq] = res[0]
            all_result_vars.append(res[0])
            # 每条指令执行完独立导出当前装配体,文件名=step_序号.stl
            lines.append("_m%d = Mesh.Mesh()" % seq)
            lines.append("for _p in [%s]:" % ", ".join(dict.fromkeys(all_result_vars)))
            lines.append("    if _p is None or _p.Volume <= 0:")
            lines.append("        continue")
            lines.append("    _vs, _fs = _p.tessellate(0.5)")
            lines.append("    _m%d.addFacets([(_vs[a], _vs[b], _vs[c]) for a, b, c in _fs])" % seq)
            _step_path = out_dir.rstrip("/") + ("/step_%d.stl" % seq)
            lines.append("_out%d = %r" % (seq, _step_path))
            lines.append("_m%d.write(_out%d)" % (seq, seq))
            lines.append("print('STL_EXPORTED:' + _out%d)" % seq)
            # 同步导出 STEP（精确 BREP，供前端 occt 预览与 CAD 软件下载）
            # 注意：不用 Part.export(列表,path)——8102 FreeCAD 0.21 / macOS 1.1.1
            # 对裸 Shape 列表静默写空 STEP(1640字节壳)。改用 Shape.exportStep
            # 实例方法；多 shape 用 makeCompound 合一(compound 几何=并集壳)
            _stp_path = out_dir.rstrip("/") + ("/step_%d.step" % seq)
            lines.append("_sh%d = [_p for _p in [%s] if _p is not None and _p.Volume > 0]"
                         % (seq, ", ".join(dict.fromkeys(all_result_vars))))
            lines.append("if _sh%d:" % seq)
            lines.append("    (Part.makeCompound(_sh%d) if len(_sh%d) > 1 else _sh%d[0]).exportStep(%r)"
                         % (seq, seq, seq, _stp_path))
            lines.append("    print('EXPORTED:' + %r)" % _stp_path)

    # 最终装配 STL（覆盖式,前端 viewer 看最新结果）
    lines.append("_m = Mesh.Mesh()")
    lines.append("for _p in [%s]:" % ", ".join(dict.fromkeys(all_result_vars)))
    lines.append("    if _p is None or _p.Volume <= 0:")
    lines.append("        continue")
    lines.append("    _vs, _fs = _p.tessellate(0.5)")
    lines.append("    _m.addFacets([(_vs[a], _vs[b], _vs[c]) for a, b, c in _fs])")
    lines.append("_astl = %r" % (out_dir.rstrip("/") + "/assembly.stl"))
    lines.append("_m.write(_astl)")
    lines.append("print('STL_EXPORTED:' + _astl)")
    # 最终装配 STEP（同上：exportStep+compound，避免 Part.export 空 STEP）
    _astp = out_dir.rstrip("/") + "/assembly.step"
    lines.append("_ash = [_p for _p in [%s] if _p is not None and _p.Volume > 0]"
                 % ", ".join(dict.fromkeys(all_result_vars)))
    lines.append("if _ash:")
    lines.append("    (Part.makeCompound(_ash) if len(_ash) > 1 else _ash[0]).exportStep(%r)" % _astp)
    lines.append("    print('EXPORTED:' + %r)" % _astp)

    # 心象快照(Primordium 拓扑,2026-09-07 用户定):每组件真实几何摘要——
    # execute_design 从 stdout 解析,run_round 写回账本 entry.topo;
    # 空间推理(759 求解/谓词验证)由此快照驱动,LLM 不再算坐标
    lines.append("import json as _tjson")
    lines.append("_topo = []")
    for _sq, _rv in result_var.items():
        lines.append("if %s is not None and %s.Volume > 0:" % (_rv, _rv))
        lines.append("    _tb = %s.BoundBox" % _rv)
        lines.append("    _topo.append({'seq': %d, 'bbox': [round(_tb.XMin,2), round(_tb.XMax,2),"
                     " round(_tb.YMin,2), round(_tb.YMax,2), round(_tb.ZMin,2), round(_tb.ZMax,2)],"
                     " 'center': [round(_tb.Center.x,2), round(_tb.Center.y,2), round(_tb.Center.z,2)],"
                     " 'volume': round(%s.Volume,2)})" % (_sq, _rv))
    lines.append("print('TOPO:' + _tjson.dumps(_topo))")

    return "\n".join(lines), {"result_var": result_var, "skipped": skipped}


def _is_geometry_error(r):
    """几何确定性错误(设计指令问题):SANITY 断言/OCC 几何异常——重试无意义。"""
    err = (r.get("stderr") or "") + (r.get("error") or "")
    return ("SANITY" in err or "OCC" in err or "geometry" in err.lower()
            or "creation of" in err)


def execute_design(ledger, project_dir, current_seq=None):
    """重放账本全部指令 → 编译 → FreeCADTool 执行 → 落账。

    返回 {ok, files, code, skipped, error}

    瞬时故障自动重试(2026-09-06 用户定:除非设计指令有问题,必须确保成功完成):
    执行失败且非几何确定性错误(SANITY/OCC 几何异常)→ 重试一次——
    覆盖 CADService 超时/瞬断/降级竞态等系统侧故障;几何错误属指令问题,
    重试无意义,如实失败并带显式标记。
    """
    entries = [(e["seq"], e["dltq"]) for e in ledger.all_entries()
               if current_seq is None or e["seq"] <= current_seq]
    if not entries:
        return {"ok": False, "error": "账本为空"}

    out_dir = os.path.join(project_dir, "cad")
    code, meta = compile_all(entries, out_dir)

    from anvil.tools.freecad import FreeCADTool
    tool = FreeCADTool(project_dir=project_dir)
    r = tool.execute_python(code)
    files = [f for f in r.get("files", []) if f.endswith((".stl", ".step"))]
    if (r.get("status") != "ok" or not files) and not _is_geometry_error(r):
        r = tool.execute_python(code)  # 系统侧瞬时故障 → 重试一次
        files = [f for f in r.get("files", []) if f.endswith((".stl", ".step"))]

    ok = (r.get("status") == "ok") and bool(files)
    # 心象快照:stdout 尾部 TOPO: 行 → [{seq,bbox,center,volume}](截尾保留,取最后一条)
    topo = {}
    _tl = [l for l in (r.get("stdout") or "").splitlines() if l.startswith("TOPO:")]
    if _tl:
        import json as _j
        try:
            for comp in _j.loads(_tl[-1][5:]):
                topo[comp.get("seq")] = comp
        except Exception:
            pass
    return {
        "ok": ok,
        "files": files,
        "code": code,
        "skipped": meta["skipped"],
        "topo": topo,
        "stdout": r.get("stdout", "")[-1500:],
        "stderr": r.get("stderr", "")[-800:],
        "error": None if ok else (r.get("stderr", "") or "FreeCAD 执行失败")[-500:],
    }
