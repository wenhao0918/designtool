"""
图元模型 — 机械设计简图的基本元素

所有图元继承 BaseElement：
  - id: 唯一标识
  - type: 图元类型
  - x, y: 位置（相对画布，mm）
  - rotation: 旋转角度（度）
  - style: 线型/颜色/线宽

图元类型：
  - Line: 线段 (x1,y1,x2,y2)
  - Rect: 矩形 (x,y,w,h,r=圆角)
  - Circle: 圆 (cx,cy,r)
  - Arc: 弧 (cx,cy,r,start_angle,end_angle)
  - Polyline: 多段线 (points[][x,y])
  - Arrow: 箭头 (from_x,from_y,to_x,to_y)
  - Dimension: 尺寸标注 (x1,y1,x2,y2,text)
  - Hinge: 铰链符号 (cx,cy,r,angle)
  - Spring: 弹簧符号 (x1,y1,x2,y2,turns)
  - Text: 文字标签 (x,y,text,size)
"""
from dataclasses import dataclass, field
from typing import List, Optional
import math

_ID_COUNTER = [0]

def new_id():
    _ID_COUNTER[0] += 1
    return f"e{_ID_COUNTER[0]}"


@dataclass
class Point:
    x: float = 0
    y: float = 0


@dataclass
class BaseElement:
    id: str = field(default_factory=new_id)
    type: str = ""
    x: float = 0
    y: float = 0
    rotation: float = 0
    layer: int = 0
    style: dict = field(default_factory=lambda: {"stroke": "#000", "stroke_width": 1.5, "fill": "none"})


@dataclass
class Line(BaseElement):
    type: str = "line"
    x1: float = 0
    y1: float = 0
    x2: float = 100
    y2: float = 0

    @property
    def length(self):
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def angle(self):
        return math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1))


@dataclass
class Rect(BaseElement):
    type: str = "rect"
    w: float = 100
    h: float = 80
    rx: float = 0


@dataclass
class Circle(BaseElement):
    type: str = "circle"
    cx: float = 0
    cy: float = 0
    r: float = 50


@dataclass
class Arc(BaseElement):
    type: str = "arc"
    cx: float = 0
    cy: float = 0
    r: float = 50
    start_angle: float = 0
    end_angle: float = 90


@dataclass
class Polyline(BaseElement):
    type: str = "polyline"
    points: List[Point] = field(default_factory=list)


@dataclass
class Arrow(BaseElement):
    type: str = "arrow"
    x1: float = 0
    y1: float = 0
    x2: float = 100
    y2: float = 0
    head_size: float = 8


@dataclass
class Dimension(BaseElement):
    type: str = "dimension"
    x1: float = 0
    y1: float = 0
    x2: float = 100
    y2: float = 0
    text: str = ""
    offset: float = 20


@dataclass
class Hinge(BaseElement):
    """铰链符号：圆+交叉线"""
    type: str = "hinge"
    cx: float = 0
    cy: float = 0
    r: float = 12


@dataclass
class Spring(BaseElement):
    """弹簧符号：锯齿线"""
    type: str = "spring"
    x1: float = 0
    y1: float = 0
    x2: float = 0
    y2: float = 100
    turns: int = 6
    width: float = 12


@dataclass
class Text(BaseElement):
    type: str = "text"
    text: str = "label"
    font_size: float = 14


class Sketch:
    """画布：包含所有图元，提供批处理操作"""

    def __init__(self, width=800, height=600):
        self.width = width
        self.height = height
        self.elements: List[BaseElement] = []
        self.grid_size = 10  # 吸附网格(mm)

    def add(self, el: BaseElement):
        self.elements.append(el)
        return el

    def remove(self, el_id: str):
        self.elements = [e for e in self.elements if e.id != el_id]

    def get_bounds(self):
        """计算所有图元的包围盒"""
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for el in self.elements:
            # 简化为各图元的近似边界
            if isinstance(el, Line):
                xs, ys = [el.x1, el.x2], [el.y1, el.y2]
            elif isinstance(el, Rect):
                xs, ys = [el.x, el.x + el.w], [el.y, el.y + el.h]
            elif isinstance(el, Circle):
                xs, ys = [el.cx - el.r, el.cx + el.r], [el.cy - el.r, el.cy + el.r]
            elif isinstance(el, Polyline) and el.points:
                xs = [p.x for p in el.points]
                ys = [p.y for p in el.points]
            else:
                continue
            min_x = min(min_x, *xs)
            max_x = max(max_x, *xs)
            min_y = min(min_y, *ys)
            max_y = max(max_y, *ys)
        return min_x, min_y, max_x, max_y
