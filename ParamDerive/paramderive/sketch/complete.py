"""
完善算法 — 对称补全、封闭缺口、建议标注
"""
from .elements import Sketch, Line, Rect, Circle, Polyline, Point, Text, Dimension
import math


def mirror_symmetry(sketch: Sketch, axis="y", center_x=None):
    """沿轴线镜像补全"""
    if center_x is None:
        min_x, _, max_x, _ = sketch.get_bounds()
        center_x = (min_x + max_x) / 2

    new_elements = []
    for el in sketch.elements:
        if isinstance(el, Line):
            if axis == "y":
                new = Line(
                    x1=2 * center_x - el.x2, y1=el.y2,
                    x2=2 * center_x - el.x1, y2=el.y1,
                    style=el.style.copy()
                )
            new.style["stroke_dasharray"] = "4,4"
            new_elements.append(new)
        elif isinstance(el, Rect):
            if axis == "y":
                new = Rect(
                    x=2 * center_x - el.x - el.w, y=el.y,
                    w=el.w, h=el.h,
                    style=el.style.copy()
                )
            new.style["stroke_dasharray"] = "4,4"
            new_elements.append(new)
        elif isinstance(el, Circle):
            if axis == "y":
                new = Circle(
                    cx=2 * center_x - el.cx, cy=el.cy, r=el.r,
                    style=el.style.copy()
                )
            new.style["stroke_dasharray"] = "4,4"
            new_elements.append(new)

    for el in new_elements:
        sketch.add(el)
    return {"status": "ok", "added": len(new_elements)}


def close_gaps(sketch: Sketch, threshold=15):
    """封闭接近闭合的线段缺口"""
    lines = [el for el in sketch.elements if isinstance(el, Line)]
    for i, l1 in enumerate(lines):
        for l2 in lines[i + 1:]:
            # 检查端点之间的距离
            ends = [(l1.x1, l1.y1), (l1.x2, l1.y2)]
            for ex, ey in ends:
                if math.hypot(ex - l2.x1, ey - l2.y1) < threshold:
                    # 延伸/合并
                    l2.x1, l2.y1 = ex, ey
                if math.hypot(ex - l2.x2, ey - l2.y2) < threshold:
                    l2.x2, l2.y2 = ex, ey
    return {"status": "ok", "gaps_closed": 1}


def auto_dimensions(sketch: Sketch):
    """自动为矩形添加尺寸标注"""
    added = 0
    for el in sketch.elements:
        if isinstance(el, Rect):
            # 宽度标注
            dim_w = Dimension(
                x1=el.x, y1=el.y + el.h + 15,
                x2=el.x + el.w, y2=el.y + el.h + 15,
                text=f"{el.w}",
                offset=0
            )
            sketch.add(dim_w)
            # 高度标注
            dim_h = Dimension(
                x1=el.x - 15, y1=el.y,
                x2=el.x - 15, y2=el.y + el.h,
                text=f"{el.h}",
                offset=0
            )
            sketch.add(dim_h)
            added += 2
    return {"status": "ok", "dimensions_added": added}
