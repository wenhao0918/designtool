"""DraftEngine 核心编排:模型 → 三视图图纸(SVG) + 结构化 meta。

架构(2026-08-18 定稿):
- 几何事实来自 FreeCAD OCC 内核:BoundBox(外形)/圆柱面(孔)/轴段
- 表达层完全自绘 SVG:三视图矩形框 + 孔投影 + 尺寸标注 + 标题栏
  (不依赖 TechDraw.projectToSVG 的 GUI 坐标系——那是之前图纸混乱的根源)
- 三视图按第一角投影法(国标 GB/T 17452)布局:俯视图在主视图正下方、
  左视图在主视图正右方;长对正(top_x==front_x)、高平齐(left_y==front_y)、
  宽相等(俯视深度==左视宽度)

流程:
1. 读模型 → bbox/孔/轴段特征 → 零件分类(轴/板/通用)
2. 轴类 → 水平主视图 + 直径/总长标注
3. 板类/通用 → 三视图(自绘矩形 + 孔投影 + 外形/孔位/孔径标注)
4. 导出附属产物:PDF(cairosvg/rsvg-convert/inkscape 逐级降级) + FCStd
5. 返回 {"svg", "pdf", "fcstd", "title", "project", "meta"}
"""

import os
from collections import Counter

from . import geometry as G
from . import svgparts as P
from . import gbstd
from . import techreq
from .features import FeatureRecognizer, PartClassifier

__version__ = "0.6.0"


def _ser_features(features):
    """features 可 JSON 化:FreeCAD Vector → list,其余原样。"""
    out = []
    for f in features:
        g = {}
        for k, v in f.items():
            if hasattr(v, "x") and hasattr(v, "y"):  # Vector
                g[k] = [round(v.x, 2), round(v.y, 2),
                        round(getattr(v, "z", 0.0), 2)]
            else:
                g[k] = v
        out.append(g)
    return out


def _export_fcstd(shape, fcstd_path):
    """导出 FreeCAD 原生文档(.FCStd),便于后续在 GUI 里继续编辑。"""
    try:
        doc = G.App.newDocument("DraftEngine")
        obj = doc.addObject("Part::Feature", "Model")
        obj.Shape = shape
        doc.saveAs(fcstd_path)
        G.App.closeDocument(doc.Name)
        return os.path.exists(fcstd_path)
    except Exception:
        return False


def _svg_to_pdf(svg_path, pdf_path, width_pt=842.0):
    """SVG → PDF。优先 cairosvg(A4 横向 842pt),降级 rsvg-convert/inkscape。"""
    try:
        import cairosvg
        cairosvg.svg2pdf(url=svg_path, write_to=pdf_path, output_width=width_pt)
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            return True
    except Exception:
        pass
    import shutil
    import subprocess
    for cmd in (["rsvg-convert", "-f", "pdf", "-o", pdf_path, svg_path],
                ["inkscape", svg_path, "--export-type=pdf",
                 "--export-filename=" + pdf_path]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    return True
            except Exception:
                pass
    return False


def _emit(on_event, payload):
    """安全触发进度回调(回调异常不影响生成)。"""
    if on_event is None:
        return
    try:
        on_event(payload)
    except Exception:
        pass


def generate_drawing(model_path, out_dir, title="", project="", filename="",
                     draft=False, annotations=None, on_event=None):
    """3D 模型 → 工程图纸 SVG。

    draft=True: 中间态——仅三视图(HLR),无标注/标题栏/PDF/FCStd,
    供 Playwright 视觉验证与 VLM 标注决策。
    annotations: VLM 标注意图列表(vlm.suggest_annotations 的输出),
    提供时按其渲染标注;否则用默认规则。
    on_event(dict): 进度回调(SSE 流式),事件形如
      {"type":"stage","stage":"load|analyze|view|annotate|export","msg":...,"data":...}"""
    if not G.HAS_FREECAD:
        return {"error": "FreeCAD 库不可用"}
    if not os.path.exists(model_path):
        return {"error": "模型文件不存在: %s" % model_path}
    _emit(on_event, {"type": "stage", "stage": "load",
                     "msg": "读取模型: %s" % os.path.basename(model_path)})
    try:
        shape = G.load_shape(model_path)
    except Exception as e:
        return {"error": "模型读取失败: %s" % str(e)}

    base = os.path.splitext(os.path.basename(model_path))[0]
    # 输出带时间戳,同名模型重复调用不覆盖历史结果
    import time
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_base = "%s_%s" % (base, stamp)
    svg_path = os.path.join(out_dir, out_base + "_drawing.svg")

    bbox = G.analyze_bbox(shape)
    L, W, H = bbox["L"], bbox["W"], bbox["H"]
    recognizer = FeatureRecognizer(shape, bbox)
    features = recognizer.recognize()
    part_type, main_axis = PartClassifier.classify(bbox, features, shape)
    holes = [f for f in features if f["type"] == "hole"]
    _emit(on_event, {"type": "stage", "stage": "analyze",
                     "msg": "特征分析: %s 类零件, %d 个孔特征"
                            % ({"shaft": "轴", "plate": "板"}.get(part_type, "通用"), len(holes)),
                     "data": {"part_type": part_type, "main_axis": main_axis,
                              "bounding_box": {"L": round(L, 2), "W": round(W, 2), "H": round(H, 2)},
                              "holes": len(holes)}})
    # 技术要求/材料推荐(规则:techreq.py)
    tech_items, material_sug = techreq.recommend(part_type, main_axis, bbox, features)
    _emit(on_event, {"type": "stage", "stage": "techreq",
                     "msg": "技术要求推荐: %d 条, 推荐材料 %s" % (len(tech_items), material_sug),
                     "data": {"items": tech_items, "material": material_sug}})

    # 轴类:专门视图;板类/通用:三视图(draft=中间态)
    if part_type == "shaft":
        r = _draw_shaft(model_path, shape, bbox, features, part_type, main_axis,
                        out_dir, svg_path, title, project, base, draft,
                        on_event=on_event, tech_items=tech_items, material=material_sug)
    else:
        r = _draw_plate(model_path, shape, bbox, features, holes, part_type, main_axis,
                        out_dir, svg_path, title, project, base, draft,
                        annotations=annotations, on_event=on_event,
                        tech_items=tech_items, material=material_sug)
    if "error" not in r and r.get("meta"):
        r["meta"]["tech_requirements"] = tech_items
        r["meta"]["material_suggestion"] = material_sug
    if "error" in r or draft:
        return r

    # ---- 附属产物:FCStd + PDF + 标题信息(对齐 REST 响应格式) ----
    _emit(on_event, {"type": "stage", "stage": "export", "msg": "导出 PDF / FCStd 附属文件"})
    fcstd_path = os.path.join(out_dir, out_base + ".FCStd")
    r["fcstd"] = fcstd_path if _export_fcstd(shape, fcstd_path) else None
    pdf_path = os.path.splitext(svg_path)[0] + ".pdf"
    r["pdf"] = pdf_path if _svg_to_pdf(svg_path, pdf_path) else None
    r["title"] = title or base
    r["project"] = project

    # ---- 国标合规自检(规则源=同一份 gbstd 知识库,闭环) ----
    try:
        from .audit import audit_svg
        comp = audit_svg(svg_path, scale_txt=r.get("scale_txt"))
        r["meta"]["compliance"] = comp
        _emit(on_event, {"type": "stage", "stage": "audit",
                         "msg": "国标合规自检: %d/%d 项通过"
                                % (comp["passed"], comp["total"]),
                         "data": {"passed": comp["passed"], "total": comp["total"]}})
    except Exception as e:
        _emit(on_event, {"type": "stage", "stage": "audit", "msg": "自检跳过: %s" % e})
    return r


def _draw_plate(model_path, shape, bbox, features, holes, part_type, main_axis,
                out_dir, svg_path, title, project, base, draft=False, annotations=None,
                on_event=None, tech_items=None, material=""):
    """FreeCAD HLR 三视图(TechDraw 内核投影,SVG 仅做序列化)。

    第一角投影法(国标 GB/T 17452):主视图(长×高)在左上,
    俯视图(长×宽)在主视图正下方,左视图(宽×高)在主视图正右方:
      top_x == front_x   → 长对正
      left_y == front_y  → 高平齐
      俯视深度 == 左视宽度 → 宽相等
    """
    L, W, H = bbox["L"], bbox["W"], bbox["H"]
    dims_notes = []

    # ---- 布局参数(自适应缩放 + 居中;图框/标题栏按 GB/T 14689/10609.1) ----
    # 绘图区:图框内,顶部留技术要求区,底部留标题栏高度
    ax0 = P.FRAME_L + 60
    ay0 = P.FRAME_T + P.TECH_H
    ax1 = P.PAGE_W - P.FRAME_R - 60
    ay1 = P.PAGE_H - P.FRAME_B - P.TITLE_H - 60
    aw, ah = ax1 - ax0, ay1 - ay0

    gap = 150  # 视图间距 px(容纳尺寸标注线+文字+箭头)
    pad = 130  # 页边留白(给外侧尺寸标注)
    # 整体布局尺寸(px):宽 = L*scale + gap + W*scale,高 = H*scale + gap + W*scale
    scale_raw = min((aw - 2 * pad - gap) / (L + W), (ah - 2 * pad - gap) / (W + H), 12.0)
    scale_raw = max(scale_raw, 1.0)
    # 吸附到 GB/T 14690 标准比例系列(标题栏"比例"栏同步)
    scale, scale_txt = gbstd.snap_scale(scale_raw)

    # 视图矩形尺寸(px)
    vw, vd, vh = L * scale, W * scale, H * scale

    # 三视图锚点(第一角:主视图左上,俯视图正下,左视图正右)
    # 整体居中(宽 = vw + gap + vd,高 = vh + gap + vd)
    group_w = vw + gap + vd
    group_h = vh + gap + vd
    ox = ax0 + (aw - group_w) / 2
    oy = ay0 + (ah - group_h) / 2

    front_x = ox
    front_y = oy                       # 主视图左上角
    top_x = front_x                    # 长对正:俯视图在主视图正下方
    top_y = front_y + vh + gap         # 俯视图左上角
    left_x = front_x + vw + gap        # 左视图在主视图正右方
    left_y = front_y                   # 高平齐

    # 坐标映射(模型 → 页面):与 HLR 视图同一语义表(page_pos),
    # 标注定位与视图朝向永远一致,不存在两套公式。
    def top_px(x):
        return top_x + G.page_pos("Top", bbox, x, bbox["ymin"], 0, L, W)[0] * scale
    def top_py(y):
        return top_y + G.page_pos("Top", bbox, bbox["xmin"], y, 0, L, W)[1] * scale
    def front_px(x):
        return front_x + G.page_pos("Front", bbox, x, 0, bbox["zmin"], L, H)[0] * scale
    def front_py(z):
        return front_y + G.page_pos("Front", bbox, 0, 0, z, L, H)[1] * scale
    def left_px(y):
        return left_x + G.page_pos("Left", bbox, 0, y, 0, W, H)[0] * scale
    def left_py(z):
        return left_y + G.page_pos("Left", bbox, 0, 0, z, W, H)[1] * scale

    # 视图边界
    top_L = top_px(bbox["xmin"]); top_R = top_px(bbox["xmax"])
    top_T = top_py(bbox["ymin"]); top_B = top_py(bbox["ymax"])
    front_L = front_px(bbox["xmin"]); front_R = front_px(bbox["xmax"])
    front_T = front_py(bbox["zmin"]); front_B = front_py(bbox["zmax"])
    left_L = left_px(bbox["ymax"]); left_R = left_px(bbox["ymin"])
    left_T = left_py(bbox["zmin"]); left_B = left_py(bbox["zmax"])

    # ---- 组装 SVG ----
    s = P.header(title, base)
    if not draft:
        s += P.tech_notes(tech_items)

    # ===== 三视图:FreeCAD TechDraw HLR 投影(可见实线/隐藏虚线) =====
    # 投影姿态由 auto_transform 三轴探针在运行时测定(转置+翻转),
    # 代码不含任何写死的投影常数。视图框:Front L×H,Top L×W,Left W×H。
    def _edge_pts(e):
        """边离散:优先偏折角(Deflection,随曲率自适应——圆弧光滑);
        失败按边长 fallback。固定 Number=24 会把圆画成 24 边形。"""
        try:
            return e.discretize(Deflection=0.1)
        except Exception:
            pass
        try:
            n = max(24, min(int(e.Length / 2.0), 360))
            return e.discretize(Number=n)
        except Exception:
            return []

    def _hlr_paths(view, ax, ay, vw_mm, vh_mm):
        out = ""
        vis, hid = G.project_hlr(shape, view)
        swap, fx, fy = G.auto_transform(view, bbox)
        mapper = G.view_mapping(vis + hid, vw_mm, vh_mm, swap, fx, fy)
        for edges, cls in ((vis, "line"), (hid, "hidden")):
            for e in edges:
                pts = _edge_pts(e)
                seg = [(ax + mapper(p)[0] * scale,
                        ay + mapper(p)[1] * scale) for p in pts]
                if len(seg) < 2:
                    continue
                d = " ".join("L%f,%f" % q for q in seg[1:])
                out += '<path d="M%f,%f %s" class="%s"/>\n' % (seg[0][0], seg[0][1], d, cls)
        return out

    # 坐标语义注意:top_T=top_py(ymin) 是俯视图页面【下】缘(模型前缘),
    # top_B=top_py(ymax) 是页面【上】缘(模型后缘,贴主视图)。front/left 同理。
    # 尺寸线/标签一律放在视图外侧:下方用 *_T+n,上方用 *_B-n。

    # 俯视图(x-y 平面,第一角在主视图正下方)
    _emit(on_event, {"type": "stage", "stage": "view", "view": "Top", "msg": "HLR 投影:俯视图"})
    s += _hlr_paths("Top", top_x, top_y, L, W)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle" font-weight="bold">俯视图</text>\n' % (
        (top_L + top_R) / 2, top_T + 40)

    # 主视图(x-z 平面)
    _emit(on_event, {"type": "stage", "stage": "view", "view": "Front", "msg": "HLR 投影:主视图"})
    s += _hlr_paths("Front", front_x, front_y, L, H)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle" font-weight="bold">主视图</text>\n' % (
        (front_L + front_R) / 2, front_T + 40)

    # ===== 左视图(y-z 平面,视线沿 +X,第一角在主视图正右) =====
    _emit(on_event, {"type": "stage", "stage": "view", "view": "Left", "msg": "HLR 投影:左视图"})
    s += _hlr_paths("Left", left_x, left_y, W, H)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle" font-weight="bold">左视图</text>\n' % (
        (left_L + left_R) / 2, left_T + 40)

    # (GB 成品图不带投影构造辅助线——第一角关系由布局本身保证)

    # ===== 尺寸标注(draft 中间态不加,留给 VLM 决策) =====
    # VLM 特征索引(与 vlm.py PROMPT 一致):holes + bosses
    vlm_feats = ([dict(kind="hole", idx=i, **{k: v for k, v in h.items() if k != "center"})
                  for i, h in enumerate(holes)]
                 + [dict(kind="boss", idx=len(holes) + i, radius=f["radius"],
                         height=f["height"], center=f["center"])
                    for i, f in enumerate(features) if f["type"] == "boss"])

    def _dim_hole_position(h):
        """孔位标注(俯视图:到左缘/前缘距离,尺寸线在视图下方/右方外侧)。"""
        hx, hy, _ = h["center"]
        hcx, hcy = top_px(hx), top_py(hy)
        d_left = hx - bbox["xmin"]
        d_bottom = hy - bbox["ymin"]
        s_ = P.dim_h_seg(top_L, hcx, top_T + 2 * P.DIM_STEP, P.fmt_dim(d_left), top_L, hcx)
        s_ += P.dim_v_seg(top_R + 2 * P.DIM_STEP, top_T, hcy, P.fmt_dim(d_bottom), top_T, hcy)
        return s_, ["孔位 X %s" % P.fmt_dim(d_left), "孔位 Y %s" % P.fmt_dim(d_bottom)]

    def _dim_hole_dia(h):
        """孔径引线标注(俯视图孔上方;同规格合并计数;沉头带大径)。"""
        cx, cy = top_px(h["center"][0]), top_py(h["center"][1])
        r = h["radius"] * scale
        same = [x for x in holes if abs(x["radius"] - h["radius"]) < 0.05
                and x.get("subtype") == h.get("subtype")]
        if h.get("subtype") == "counterbore":
            txt = "Φ%s 沉头 Φ%s" % (P.fmt_dim(h["radius"] * 2),
                                    P.fmt_dim(h.get("counterbore_diameter", 0)))
        else:
            txt = ("%d-Φ%s" % (len(same), P.fmt_dim(h["radius"] * 2))
                   if len(same) > 1 else "Φ%s" % P.fmt_dim(h["radius"] * 2))
        ty = cy - r - P.DIM_STEP
        s_ = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>\n' % (cx, cy - r - 8, cx, ty + 12)
        s_ += '<text x="%f" y="%f" class="text" text-anchor="middle">%s</text>\n' % (cx, ty, txt)
        return s_, [txt]

    def _dim_side_hole(h):
        """X/Y 向侧孔标注:孔口圆所在视图(正对视线)引线标 Φ。"""
        dia = h["radius"] * 2
        txt = "Φ%s" % P.fmt_dim(dia)
        if h["axis"] == 0:  # X 向孔:主视图(视线 -Y)孔口在右侧面,圆心 (x=xmax, z)
            cx = front_R - 50
            cy = front_py(h["center"][2])
        else:  # Y 向孔:左视图(视线 +X)孔口在前面(y 小),圆心画在左视图
            cx = left_L + 30
            cy = left_py(h["center"][2])
        ty = cy - 80
        s_ = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>\n' % (cx, cy - 8, cx, ty + 10)
        s_ += '<text x="%f" y="%f" class="text" text-anchor="middle">%s</text>\n' % (cx, ty, txt)
        return s_, [txt]

    def _dim_boss_height(f):
        """凸台高度标注(主视图:凸台右侧面外侧竖直尺寸)。"""
        bx, by = f["center"].x, f["center"].y
        z0, z1 = f["zmin"], f["zmax"]
        x_r = front_px(bx) + f["radius"] * scale + P.DIM_STEP
        y0, y1 = front_py(z0), front_py(z1)
        s_ = P.dim_v_seg(x_r, y0, y1, P.fmt_dim(f["height"]), y0, y1)
        return s_, ["凸台高 %s" % P.fmt_dim(f["height"])]

    def _dim_wall(w):
        """壁厚/内外径引线标注(主视图)。球体: SΦ外径/SΦ内径/t壁厚
        (GB 球面直径前缀 SΦ);三条引线分角度避免重叠。"""
        import math as _m
        cx = (front_L + front_R) / 2
        cy = (front_T + front_B) / 2
        r_out_px = w["r_out"] * scale
        r_in_px = w["r_in"] * scale
        notes = []

        def _leader(angle_deg, r_target, txt):
            a = _m.radians(angle_deg)
            ca, sa = _m.cos(a), _m.sin(a)
            px, py = cx + ca * r_target, cy - sa * r_target
            lead = r_out_px + 130
            tx, ty = cx + ca * lead, cy - sa * lead
            frag = '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="dim"/>\n' % (tx, ty, px, py)
            frag += '<text x="%.1f" y="%.1f" class="text">%s</text>\n' % (tx + 8, ty - 8, txt)
            return frag

        if w.get("subtype") == "sphere":
            s_ = _leader(135, r_out_px, "SΦ%s" % P.fmt_dim(w["r_out"] * 2))
            s_ += _leader(45, r_in_px, "SΦ%s" % P.fmt_dim(w["r_in"] * 2))
            notes += ["外径 SΦ%s" % P.fmt_dim(w["r_out"] * 2),
                      "内径 SΦ%s" % P.fmt_dim(w["r_in"] * 2)]
            t_txt = "壁厚 t%s" % P.fmt_dim(w["thickness"])
            s_ += _leader(-45, (r_out_px + r_in_px) / 2, t_txt)
            notes.append(t_txt)
        else:
            t_txt = "壁厚 t%s" % P.fmt_dim(w["thickness"])
            s_ = _leader(45, (r_out_px + r_in_px) / 2, t_txt)
            notes.append(t_txt)
        return s_, notes

    def _render_annotation(a):
        """按 VLM 意图渲染一个标注。返回 (svg片段, notes)。"""
        kind = a.get("kind")
        tgt = a.get("target")
        if kind == "overall-length":
            return P.dim_h(top_L, top_R, top_T + P.DIM_STEP, P.fmt_dim(L)), ["外形 L %s" % P.fmt_dim(L)]
        if kind == "overall-width":
            return P.dim_v(top_R + P.DIM_STEP, top_B, top_T, P.fmt_dim(W)), ["外形 W %s" % P.fmt_dim(W)]
        if kind == "overall-height":
            return P.dim_v(front_L - P.DIM_STEP, front_T, front_B, P.fmt_dim(H)), ["外形 H %s" % P.fmt_dim(H)]
        if kind == "hole-position" and tgt is not None and tgt < len(holes):
            return _dim_hole_position(holes[tgt])
        if kind == "hole-dia" and tgt is not None and tgt < len(holes):
            if holes[tgt]["axis"] != 2:
                return _dim_side_hole(holes[tgt])
            return _dim_hole_dia(holes[tgt])
        if kind == "boss-height":
            bosses = [f for f in features if f["type"] == "boss"]
            if tgt is not None and 0 <= tgt - len(holes) < len(bosses):
                return _dim_boss_height(bosses[tgt - len(holes)])
        if kind == "wall-thickness":
            walls = [f for f in features if f["type"] == "wall"]
            if walls:
                return _dim_wall(walls[tgt if tgt is not None and 0 <= tgt < len(walls) else 0])
        return "", []

    if not draft:
        _emit(on_event, {"type": "stage", "stage": "annotate",
                         "msg": "尺寸标注(%s)+ 标题栏"
                                % ("VLM 决策" if annotations else "总体尺寸 + 孔位/孔径")})
        if annotations:
            # VLM 决策的标注意图 → 确定性渲染
            for a in annotations:
                frag, notes = _render_annotation(a)
                s += frag
                dims_notes += notes
        else:
            # 默认规则:总体尺寸 + 首孔位 + 孔径分组
            for a in ({"kind": "overall-length"}, {"kind": "overall-width"},
                      {"kind": "overall-height"}):
                s += _render_annotation(a)[0]
            dims_notes.append("外形 %s x %s x %s" % (P.fmt_dim(L), P.fmt_dim(W), P.fmt_dim(H)))
            z_holes = [h for h in holes if h["axis"] == 2]
            skip_dia = {round(h.get("counterbore_diameter", 0), 2)
                        for h in z_holes if h.get("subtype") == "counterbore"}
            done_dia = set()
            for h in z_holes:
                dia = round(h["radius"] * 2, 2)
                if dia in skip_dia or dia in done_dia:
                    continue
                done_dia.add(dia)
                frag, notes = _dim_hole_dia(h)
                s += frag
                dims_notes += notes
            if z_holes:
                frag, notes = _dim_hole_position(z_holes[0])
                s += frag
                dims_notes += notes
            # 侧孔(X/Y 向):孔口圆所在视图引线标 Φ
            for h in holes:
                if h["axis"] != 2:
                    frag, notes = _dim_side_hole(h)
                    s += frag
                    dims_notes += notes
            # 壁厚(空心壳体):引线标注 t
            for w in [f for f in features if f["type"] == "wall"]:
                frag, notes = _dim_wall(w)
                s += frag
                dims_notes += notes

    # ===== 标题栏(draft 中间态不加,终稿再加) =====
    if not draft:
        s += P.title_block(title, base, project, material, scale_txt)
    s += '</svg>\n'

    try:
        with open(svg_path, "w") as f:
            f.write(s)
    except Exception as e:
        return {"error": "SVG 写入失败: %s" % str(e)}

    meta = {
        "tool": "DraftEngine",
        "version": __version__,
        "source": os.path.basename(model_path),
        "part_type": part_type,
        "main_axis": main_axis,
        "bounding_box": {"L": round(L, 2), "W": round(W, 2), "H": round(H, 2)},
        "features": _ser_features(features),
        "holes": [{"dia": round(h["radius"] * 2, 2), "axis": "XYZ"[h["axis"]],
                    "center": [round(v, 1) for v in h["center"]],
                    "depth": round(h["depth"], 1), "subtype": h.get("subtype", "through")}
                   for h in holes],
        "walls": [{"thickness": w["thickness"], "subtype": w.get("subtype", "sphere"),
                   "r_out": w["r_out"], "r_in": w["r_in"]}
                  for w in features if w["type"] == "wall"],
        "vlm_features": [
            {"idx": i, "kind": "hole", "dia": round(h["radius"] * 2, 2),
             "axis": "XYZ"[h["axis"]],
             "center": [round(v, 1) for v in h["center"]],
             "subtype": h.get("subtype", "through")}
            for i, h in enumerate(holes)] + [
            {"idx": len(holes) + i, "kind": "boss",
             "dia": round(f["radius"] * 2, 2),
             "center": [round(f["center"].x, 1), round(f["center"].y, 1)],
             "height": round(f["height"], 1)}
            for i, f in enumerate(features) if f["type"] == "boss"] + [
            {"idx": len(holes) + len([f for f in features if f["type"] == "boss"]) + i,
             "kind": "wall", "thickness": w["thickness"]}
            for i, w in enumerate([f for f in features if f["type"] == "wall"])],
        "dimensions": dims_notes,
        "scale": scale_txt,
        "views": ["Front", "Top", "Left"],
    }
    if annotations:
        meta["annotations"] = annotations
    return {"svg": svg_path, "pdf": None, "meta": meta}


def _draw_shaft(model_path, shape, bbox, features, part_type, main_axis,
                out_dir, svg_path, title, project, base, draft=False, on_event=None,
                tech_items=None, material=""):
    """轴类:水平主视图 + 直径/长度标注(自绘,无投影依赖)。"""
    _emit(on_event, {"type": "stage", "stage": "view", "view": "ShaftFront",
                     "msg": "轴类专用主视图(%s向)" % main_axis})
    L, W, H = bbox["L"], bbox["W"], bbox["H"]
    axis = "XYZ".index(main_axis)
    total_len = (L, W, H)[axis]
    segs = sorted([f for f in features if f["type"] == "shaft_segment"],
                  key=lambda f: f["axial_pos"])
    if not segs:
        segs = sorted([f for f in features if f["type"] == "hole"],
                      key=lambda f: f["center"][axis])
    if not segs:
        return {"error": "轴类零件无轴段特征"}
    max_r = max(f["radius"] for f in segs) if segs else max(L, W, H) / 2

    ax0 = P.FRAME_L + 60
    ay0 = P.FRAME_T + P.TECH_H
    ax1 = P.PAGE_W - P.FRAME_R - 60
    ay1 = P.PAGE_H - P.FRAME_B - P.TITLE_H - 60
    aw, ah = ax1 - ax0, ay1 - ay0
    scale_raw = min(aw * 0.8 / total_len, ah * 0.5 / (2 * max_r), 14.0)
    scale_raw = max(scale_raw, 1.0)
    scale, scale_txt = gbstd.snap_scale(scale_raw)

    start_x = ax0 + 60
    center_y = ay0 + ah * 0.45

    s = P.header(title, base)
    s += P.tech_notes(tech_items)
    s += '<text x="%f" y="%f" class="text" font-weight="bold">主视图(轴类,%s向)</text>\n' % (
        (ax0 + ax1) / 2, ay0 - 20, main_axis)

    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="centerline"/>\n' % (
        start_x - 40, center_y, start_x + total_len * scale + 40, center_y)

    dims_notes = ["轴类 %s向, 总长 %s" % (main_axis, P.fmt_dim(total_len))]
    prev_end = start_x
    for i, seg in enumerate(segs):
        r = seg["radius"]
        if i < len(segs) - 1:
            seg_len = segs[i + 1]["axial_pos"] - seg["axial_pos"]
        else:
            seg_len = total_len - (seg["axial_pos"] - bbox["xmin" if axis == 0 else "ymin" if axis == 1 else "zmin"])
        seg_len = max(seg_len, 0.5)
        x0 = prev_end
        x1 = prev_end + seg_len * scale
        s += '<rect x="%f" y="%f" width="%f" height="%f" class="line"/>\n' % (
            x0, center_y - r * scale, x1 - x0, 2 * r * scale)
        s += '<text x="%f" y="%f" class="text" text-anchor="middle">Φ%s</text>\n' % (
            (x0 + x1) / 2, center_y - r * scale - 20, P.fmt_dim(2 * r))
        dims_notes.append("Φ%s" % P.fmt_dim(2 * r))
        prev_end = x1

    y_dim = center_y + max_r * scale + 120
    s += P.dim_h(start_x, prev_end, y_dim, P.fmt_dim(total_len))

    s += P.title_block(title, base, project, material, scale_txt)
    s += '</svg>\n'
    try:
        with open(svg_path, "w") as f:
            f.write(s)
    except Exception as e:
        return {"error": "SVG 写入失败: %s" % str(e)}

    meta = {
        "tool": "DraftEngine",
        "version": __version__,
        "source": os.path.basename(model_path),
        "part_type": part_type,
        "main_axis": main_axis,
        "bounding_box": {"L": round(L, 2), "W": round(W, 2), "H": round(H, 2)},
        "features": features,
        "dimensions": dims_notes,
        "scale": scale_txt,
        "views": ["ShaftFront"],
    }
    return {"svg": svg_path, "pdf": None, "meta": meta}
