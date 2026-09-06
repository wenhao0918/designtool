"""机械组件画法 — 齿轮、铰链、电机等标准件。

这些组件在 FreeCAD 中没有单一原语对应，
export 描述性文本让 LLM 自主决定建模策略。
"""

NAME = "mechanical"
DESCRIPTION = "机械标准件/装配件：齿轮、铰链、推杆、电机、轴承、丝杠、滑轨、滚轮"

REGISTRY: dict[str, str] = {
    "gear": "mechanical",
    "hinge": "mechanical",
    "actuator": "mechanical",
    "motor": "mechanical",
    "bearing": "mechanical",
    "screw": "mechanical",
    "slider": "mechanical",
    "wheel": "mechanical",
}

_LABELS: dict[str, str] = {
    "gear": "齿轮",
    "hinge": "铰链",
    "actuator": "电动推杆",
    "motor": "电机",
    "bearing": "轴承",
    "screw": "丝杠",
    "slider": "滑轨",
    "wheel": "滚轮",
}


def component_to_part(component: dict, idx: int) -> dict | None:
    """机械组件暂不生成 FreeCAD 原语，返回 None（由 LLM 决定）。"""
    ctype = component.get("type", "")
    label = _LABELS.get(ctype, ctype)
    x = component.get("x", 0)
    y = component.get("y", 0)
    # 机械组件不返回 part dict，只写入描述文本
    # sketch.py 的 scene_to_cad_instructions 会处理这类
    return None


def component_description(component: dict, idx: int) -> str:
    """生成机械组件的建模建议文本。"""
    ctype = component.get("type", "")
    label = _LABELS.get(ctype, ctype)
    x = component.get("x", 0)
    y = component.get("y", 0)
    return (
        f"# {label} @({x:.0f},{y:.0f}) — 无直接 CAD 原语，请用多原语组合或外部导入\n"
        f"# 建议：用 cylinder+shell_box+pattern 搭建{label}，或导入标准件 STEP"
    )
