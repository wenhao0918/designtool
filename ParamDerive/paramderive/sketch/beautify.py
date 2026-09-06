"""
美化算法 — 直线化、对齐、网格吸附、均匀分布
"""
import math
from .elements import Sketch, Line, Rect, Circle, Point, Polyline


def snap_to_grid(val, grid=10):
    """吸附到最近网格点"""
    return round(val / grid) * grid


def beautify_lines(sketch: Sketch):
    """
    直线化：将接近水平的线转为水平，接近垂直的转为垂直
    接近45度的转为45度
    """
    for el in sketch.elements:
        if isinstance(el, Line):
            angle = abs(el.angle % 180)
            if angle < 5 or angle > 175:
                # 水平化
                el.y2 = el.y1
            elif 85 < angle < 95:
                # 垂直化
                el.x2 = el.x1
            elif 40 < angle < 50:
                # 45度
                length = el.length
                direction = 1 if el.angle > 0 else -1
                el.x2 = el.x1 + length * math.cos(math.radians(45)) * direction
                el.y2 = el.y1 + length * math.sin(math.radians(45)) * direction
            elif 130 < angle < 140:
                length = el.length
                el.x2 = el.x1 - length * math.cos(math.radians(45))
                el.y2 = el.y1 + length * math.sin(math.radians(45))


def snap_to_grid_all(sketch: Sketch):
    """所有顶点吸附网格"""
    for el in sketch.elements:
        if isinstance(el, Line):
            el.x1 = snap_to_grid(el.x1, sketch.grid_size)
            el.y1 = snap_to_grid(el.y1, sketch.grid_size)
            el.x2 = snap_to_grid(el.x2, sketch.grid_size)
            el.y2 = snap_to_grid(el.y2, sketch.grid_size)
        elif isinstance(el, Rect):
            el.x = snap_to_grid(el.x, sketch.grid_size)
            el.y = snap_to_grid(el.y, sketch.grid_size)
            el.w = snap_to_grid(el.w, sketch.grid_size)
            el.h = snap_to_grid(el.h, sketch.grid_size)
        elif isinstance(el, Circle):
            el.cx = snap_to_grid(el.cx, sketch.grid_size)
            el.cy = snap_to_grid(el.cy, sketch.grid_size)
            el.r = max(snap_to_grid(el.r, sketch.grid_size), sketch.grid_size)
        elif isinstance(el, Polyline):
            for p in el.points:
                p.x = snap_to_grid(p.x, sketch.grid_size)
                p.y = snap_to_grid(p.y, sketch.grid_size)


def align_centers(sketch: Sketch):
    """水平或垂直居中对齐选中的图元"""
    if not sketch.elements:
        return
    # 计算整体的中心
    min_x, min_y, max_x, max_y = sketch.get_bounds()
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    # 每个图元的中心对齐到整体中心
    for el in sketch.elements:
        if isinstance(el, Line):
            cx = (el.x1 + el.x2) / 2
            cy = (el.y1 + el.y2) / 2
            dx = center_x - cx
            dy = center_y - cy
            el.x1 += dx
            el.x2 += dx
            el.y1 += dy
            el.y2 += dy
        elif isinstance(el, Rect):
            el.x = center_x - el.w / 2
            el.y = center_y - el.h / 2
        elif isinstance(el, Circle):
            el.cx = center_x
            el.cy = center_y


def distribute_evenly(sketch: Sketch, axis="x"):
    """均匀分布选中图元"""
    items = [el for el in sketch.elements if isinstance(el, (Rect, Circle))]
    if len(items) < 3:
        return
    if axis == "x":
        positions = sorted(
            [(getattr(el, 'cx' if isinstance(el, Circle) else 'x') + getattr(el, 'w', 0) / 2, el)
             for el in items],
            key=lambda x: x[0]
        )
        first = positions[0][0]
        last = positions[-1][0]
        step = (last - first) / (len(positions) - 1)
        for i, (_, el) in enumerate(positions):
            if isinstance(el, Circle):
                el.cx = first + i * step
            elif isinstance(el, Rect):
                el.x = first + i * step - el.w / 2


def beautify(sketch: Sketch):
    """一键美化：网格吸附 + 直线化"""
    snap_to_grid_all(sketch)
    beautify_lines(sketch)
    return {"status": "ok", "elements_count": len(sketch.elements)}
