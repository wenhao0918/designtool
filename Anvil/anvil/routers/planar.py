"""平面几何画法 — 圆、矩形、多边形、线、箭头。

平面图形映射为薄片/拉伸截面。
"""

import math

NAME = "planar"
DESCRIPTION = "平面几何图形：圆、矩形、三角形、菱形、五边形、六边形、直线、箭头"

REGISTRY: dict[str, str] = {
    "circle": "cylinder",           # 薄圆柱（垫片）
    "square": "shell_box",          # 薄壳板
    "triangle": "extruded_profile",  # 拉伸多边形
    "diamond": "extruded_profile",
    "pentagon": "extruded_profile",
    "hexagon": "extruded_profile",
    "line": None,                    # 辅助线，不生成模型
    "arrow": None,                   # 箭头标注，不生成模型
}

_LABELS: dict[str, str] = {
    "circle": "圆",
    "square": "矩形",
    "triangle": "三角形",
    "diamond": "菱形",
    "pentagon": "五边形",
    "hexagon": "六边形",
    "line": "直线",
    "arrow": "箭头",
}

_POLYGON_SIDES: dict[str, int] = {
    "triangle": 3,
    "diamond": 4,
    "pentagon": 5,
    "hexagon": 6,
}


def component_to_part(component: dict, idx: int) -> dict | None:
    """平面几何 → generate_model 的 part 参数。"""
    ctype = component.get("type", "")
    if ctype not in REGISTRY or REGISTRY[ctype] is None:
        return None

    x = component.get("x", 0)
    y = component.get("y", 0)
    name = f"part_{idx}"

    if ctype == "circle":
        r = round(component.get("size", 50) / 2, 1)
        return {
            "type": "cylinder",
            "params": {"name": name, "r": r, "h": 3, "pos": (x, y, 0)},
        }

    if ctype == "square":
        sz = round(component.get("size", 50), 1)
        return {
            "type": "shell_box",
            "params": {"name": name, "L": sz, "W": sz, "H": 3, "t": 2, "pos": (x, y, 0)},
        }

    if ctype in _POLYGON_SIDES:
        sz = round(component.get("size", 50), 1)
        r = sz / 2
        n = _POLYGON_SIDES[ctype]
        pts = [
            (round(r * math.cos(2 * math.pi * i / n - math.pi / 2), 1),
             round(r * math.sin(2 * math.pi * i / n - math.pi / 2), 1))
            for i in range(n)
        ]
        return {
            "type": "extruded_profile",
            "params": {
                "name": name,
                "profile_points": pts,
                "height": 5,
                "pos": (x, y, 0),
            },
        }

    return None


def component_label(ctype: str) -> str:
    """取组件的中文标签。"""
    return _LABELS.get(ctype, ctype)
