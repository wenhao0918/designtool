"""
识别工具 — 从自由绘制的点推断标准图元
"""
from .elements import Sketch, Line, Rect, Circle, Arrow, Point
import math


def recognize_from_points(points, sketch=None):
    """
    从一系列点识别出图元类型

    输入: points = [(x1,y1), (x2,y2), ...]
    返回: (element, confidence)
    """
    if sketch is None:
        sketch = Sketch()

    n = len(points)
    if n < 2:
        return None, 0

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx, cy = sum(xs) / n, sum(ys) / n

    # 判断是否近似直线
    line_fit_error = _line_fit_error(points)

    if n == 2 or (line_fit_error < 5 and n < 8):
        # 直线
        el = Line(x1=points[0][0], y1=points[0][1],
                   x2=points[-1][0], y2=points[-1][1])
        conf = max(0, 1 - line_fit_error / 20)
        return el, conf

    # 判断是否近似圆
    rad = sum(math.hypot(x - cx, y - cy) for x, y in points) / n
    circle_error = sum(abs(math.hypot(x - cx, y - cy) - rad) for x, y in points) / n

    if circle_error < rad * 0.15:
        el = Circle(cx=cx, cy=cy, r=rad)
        conf = max(0, 1 - circle_error / (rad * 0.3))
        return el, conf

    # 判断是否矩形（4条近似直线的分段）
    # 判断是否箭头（主线+三角形头）

    return None, 0


def _line_fit_error(points):
    """点到最佳拟合直线的平均距离"""
    if len(points) < 3:
        return 0
    x1, y1 = points[0]
    x2, y2 = points[-1]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1:
        return 0
    errors = []
    for x, y in points:
        dist = abs(dx * (y1 - y) - (x1 - x) * dy) / length
        errors.append(dist)
    return sum(errors) / len(errors)
