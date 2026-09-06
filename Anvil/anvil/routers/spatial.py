"""立体几何画法 — 长方体、球体、圆柱、圆锥、棱锥。

核心类别，所有组件有明确的 FreeCAD 原语对应。
"""

import math

NAME = "spatial"
DESCRIPTION = "立体几何体：长方体、正方体、球体、圆柱、圆锥、棱锥"

REGISTRY: dict[str, str] = {
    "cuboid": "shell_box",
    "cube": "shell_box",
    "sphere": "sphere",
    "cylinder": "cylinder",
    "cone": "revolved_solid",
    "rcone": "revolved_solid",
    "pyramid": "cone",
}

_LABELS: dict[str, str] = {
    "cuboid": "长方体",
    "cube": "立方体",
    "sphere": "球体",
    "cylinder": "圆柱",
    "cone": "圆锥",
    "rcone": "正圆锥",
    "pyramid": "棱锥",
}


def _vec_len(v: dict) -> float:
    return math.hypot(v.get("x", 0), v.get("y", 0))


def component_to_part(component: dict, idx: int) -> dict | None:
    """立体几何 → generate_model 的 part 参数。"""
    ctype = component.get("type", "")
    if ctype not in REGISTRY:
        return None

    x = component.get("x", 0)
    y = component.get("y", 0)
    name = f"part_{idx}"

    # —— 长方体：三向量模式 ——
    if ctype == "cuboid" and component.get("cuboidVectors"):
        cv = component["cuboidVectors"]
        L = round(_vec_len(cv["frontTop"]), 1)
        H = round(_vec_len(cv["frontLeft"]), 1)
        D = round(_vec_len(cv["depthVec"]), 1)
        if L < 1 or H < 1 or D < 1:
            return None
        return {
            "type": "shell_box",
            "params": {"name": name, "L": L, "W": D, "H": H, "t": 2, "pos": (x, y, 0)},
        }

    # —— 立方体 ——
    if ctype == "cube":
        sz = round(component.get("size", 50), 1)
        return {
            "type": "shell_box",
            "params": {"name": name, "L": sz, "W": sz, "H": sz, "t": 2, "pos": (x, y, 0)},
        }

    # —— 球体 ——
    if ctype == "sphere":
        r = round(component.get("size", 50), 1)
        return {
            "type": "sphere",
            "params": {"name": name, "r": r, "pos": (x, y, 0)},
        }

    # —— 圆柱 ——
    if ctype == "cylinder":
        h = round(component.get("size", 50), 1)
        r = round(component.get("cylinderRadius", h / 2), 1)
        return {
            "type": "cylinder",
            "params": {"name": name, "r": r, "h": h, "pos": (x, y, 0)},
        }

    # —— 圆锥：revolved_solid（三角形截面回转） ——
    if ctype in ("cone", "rcone"):
        r = round(component.get("coneRadius", 25), 1)
        tip = component.get("coneTip", {})
        dx = tip.get("x", x) - x
        dy = tip.get("y", y) - y
        h = round(math.hypot(dx, dy), 1)
        if h < 1:
            h = round(component.get("size", 50), 1)
        return {
            "type": "revolved_solid",
            "params": {
                "name": name,
                "profile_points": [(0, 0), (r, 0), (0, h)],
                "axis_start": (0, 0, 0),
                "axis_end": (0, 1, 0),
                "angle_deg": 360,
                "pos": (x, y, 0),
            },
        }

    # —— 棱锥 ——
    if ctype == "pyramid":
        sz = round(component.get("size", 50), 1)
        r = round(sz * 0.35, 1)
        h = round(sz * 0.8, 1)
        return {
            "type": "revolved_solid",
            "params": {
                "name": name,
                "profile_points": [(0, 0), (r, 0), (0, h)],
                "axis_start": (0, 0, 0),
                "axis_end": (0, 1, 0),
                "angle_deg": 360,
                "pos": (x, y, 0),
            },
        }

    return None


def component_label(ctype: str) -> str:
    """取组件的中文标签。"""
    return _LABELS.get(ctype, ctype)


def component_description(component: dict, idx: int) -> str:
    """生成立体几何的 CAD 原语描述文本。"""
    import math
    ctype = component.get("type", "")
    x = component.get("x", 0)
    y = component.get("y", 0)
    name = f"part_{idx}"
    label = _LABELS.get(ctype, ctype)
    prim = REGISTRY.get(ctype, "")

    if ctype == "cuboid" and component.get("cuboidVectors"):
        cv = component["cuboidVectors"]
        L = round(_vec_len(cv["frontTop"]), 1)
        H = round(_vec_len(cv["frontLeft"]), 1)
        D = round(_vec_len(cv["depthVec"]), 1)
        return (
            f'{prim}("{name}", L={L}, W={D}, H={H}, t=2, pos=({x:.0f},{y:.0f},0))\n'
            f"  # 长方体：正面 L={L}×H={H}，深={D}，锚点({x:.0f},{y:.0f})"
        )

    if ctype in ("cuboid", "cube"):
        sz = round(component.get("size", 50), 1)
        return f'{prim}("{name}", L={sz}, W={sz}, H={sz}, t=2, pos=({x:.0f},{y:.0f},0))  # {label}'

    if ctype == "sphere":
        r = round(component.get("size", 50), 1)
        return f'{prim}("{name}", r={r}, pos=({x:.0f},{y:.0f},0))  # {label}: 半径{r}'

    if ctype == "cylinder":
        h = round(component.get("size", 50), 1)
        r = round(component.get("cylinderRadius", h / 2), 1)
        return f'{prim}("{name}", r={r}, h={h}, pos=({x:.0f},{y:.0f},0))  # {label}: r={r}, h={h}'

    if ctype == "cone":
        r = round(component.get("coneRadius", 25), 1)
        tip = component.get("coneTip", {})
        dx = tip.get("x", component.get("x", 0)) - component.get("x", 0)
        dy = tip.get("y", component.get("y", 0)) - component.get("y", 0)
        h = round(math.hypot(dx, dy), 1) or round(component.get("size", 50), 1)
        return f'revolved_solid("{name}", profile_points=[(0,0),({r},0),(0,{h})], axis_start=(0,0,0), axis_end=(0,1,0), angle_deg=360, pos=({x:.0f},{y:.0f},0))  # {label}: r={r}, h={h}'

    if ctype == "pyramid":
        sz = round(component.get("size", 50), 1)
        r = round(sz * 0.35, 1)
        h = round(sz * 0.8, 1)
        return f'revolved_solid("{name}", profile_points=[(0,0),({r},0),(0,{h})], axis_start=(0,0,0), axis_end=(0,1,0), angle_deg=360, pos=({x:.0f},{y:.0f},0))  # {label}'

    return None
