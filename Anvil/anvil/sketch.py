"""手绘草图识别 — 用户用手绘表达设计意图，AI 视觉模型理解并生成结构化设计需求。

流程: 手绘 PNG → vision 模型识别 (moonshot) → 设计意图 JSON → 送入 agent 建模
"""

import base64
import json
import os
from pathlib import Path

from .llm import chat_vision

# 识别提示词：要求视觉模型把手绘草图转成结构化设计需求
SKETCH_PROMPT = """你是机械设计工程师，正在解读工程师的手绘草图。请仔细识别图片内容，输出结构化的设计需求。

分析要点：
1. 这是什么零件/结构？（如：U型槽、壳体、铰链座、轴、支架等）
2. 有哪些关键尺寸标注？（长度、宽度、高度、孔径、壁厚、角度等）
3. 结构特征（开口方向、端壁、孔位、法兰、加强筋等）
4. 可能的用途（如：便盆底座、铰链连接件、密封槽等）

输出格式（严格JSON，不要其他文字）：
{
  "type": "零件类型",
  "dimensions": {"参数名": "数值+单位", ...},
  "features": ["结构特征1", "结构特征2", ...],
  "description": "完整的设计意图描述（2-3句话，供建模使用）",
  "suggested_name": "建议的英文零件名（小写下划线，如u_channel_base）"
}
"""


def recognize_sketch(image_bytes: bytes, user_id: int | None = None) -> dict:
    """识别手绘草图，返回设计意图 dict。

    Args:
        image_bytes: PNG/JPEG 图片原始字节

    Returns:
        dict: {type, dimensions, features, description, suggested_name}
        识别失败时返回 {error: 错误信息}
    """
    try:
        b64 = base64.b64encode(image_bytes).decode()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SKETCH_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ]
        resp = chat_vision(messages, temperature=0.2, user_id=user_id)
        content = resp.choices[0].message.content
        # 提取 JSON（模型可能带 ```json 包裹）
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        # 找第一个 { 到最后一个 }
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
        result = json.loads(content)
        return result
    except json.JSONDecodeError as e:
        return {"error": f"识别结果解析失败: {e}", "raw": content if "content" in dir() else ""}
    except Exception as e:
        return {"error": f"视觉识别失败: {e}"}


def sketch_to_message(intent: dict) -> str:
    """把识别结果转成 agent 可理解的设计需求文本。"""
    if "error" in intent:
        return f"[草图识别失败] {intent['error']}"

    dims = intent.get("dimensions", {})
    dim_str = "、".join(f"{k}={v}" for k, v in dims.items()) if dims else "未标注"

    features = intent.get("features", [])
    feat_str = "；".join(features) if features else "无特殊特征"

    desc = intent.get("description", "")

    msg = (
        f"【手绘草图识别结果】\n"
        f"零件类型: {intent.get('type', '未知')}\n"
        f"尺寸: {dim_str}\n"
        f"结构特征: {feat_str}\n"
        f"设计意图: {desc}\n"
        f"建议零件名: {intent.get('suggested_name', 'part')}\n\n"
        f"请根据以上设计意图进行参数化建模。"
    )
    return msg


# === 结构化场景 → CAD 原语 ===

def scene_to_cad_instructions(scene: dict) -> str:
    """把结构化场景 JSON 转成 CAD 原语调用指令文本，供 agent 直接执行。

    调度各 category router 的 component_description 生成描述。
    """
    from .routers import CATEGORY_ROUTERS, mechanical

    components = scene.get("components", [])
    if not components:
        return ""

    lines = [
        "【结构化场景 — CAD 原语映射】",
        f"以下 {len(components)} 个组件已从手绘精确提取，可直接用于参数化建模。",
        "每个组件均给出对应的 CAD 原语调用，坐标单位 mm（1px≈1mm）。",
        "",
        "--- CAD 原语指令 ---",
    ]

    cad_lines = []
    unknown_lines = []
    has_cad = False

    for idx, c in enumerate(components):
        ctype = c.get("type", "")
        # 调度到 category router
        desc = None
        for cr in CATEGORY_ROUTERS:
            if ctype in cr.REGISTRY:
                if hasattr(cr, "component_description"):
                    desc = cr.component_description(c, idx + 1)
                else:
                    # 有原语映射但没有 component_description → 生成标准描述
                    desc = _default_component_description(c, idx + 1, cr)
                break

        if desc is None:
            continue
        if desc.startswith("#"):
            unknown_lines.append(desc)
        else:
            cad_lines.append(desc)
            has_cad = True

    if cad_lines:
        lines.append("")
        lines.append("# 可直接执行的 CAD 原语（按需调整尺寸和位置）：")
        for cl in cad_lines:
            lines.append(cl)

    if unknown_lines:
        lines.append("")
        lines.append("# 以下组件无直达原语，需 LLM 自主决定建模策略：")
        for ul in unknown_lines:
            lines.append(ul)

    if not has_cad and not unknown_lines:
        return ""

    lines.append("")
    lines.append("--- 说明 ---")
    lines.append("以上坐标和尺寸来自用户手绘的结构化提取。")
    lines.append("请结合视觉识别的语义信息（零件用途、装配关系）调整参数并执行建模。")
    lines.append("优先使用给出的原语调用，直接执行即可；")
    lines.append("需要调整的标注清楚，零件之间的装配关系由你判断。")

    return "\n".join(lines)


def _default_component_description(c: dict, idx: int, router) -> str:
    """为有原语但无自定义描述的 router 生成标准 CAD 指令。"""
    import math
    ctype = c.get("type", "")
    x = c.get("x", 0)
    y = c.get("y", 0)
    prim = router.REGISTRY.get(ctype, "")
    name = f"part_{idx}"
    label = router.component_label(ctype) if hasattr(router, "component_label") else ctype
    size = c.get("size", 50)

    if ctype in ("cuboid", "cube", "square"):
        return f'{prim}("{name}", L={size:.0f}, W={size:.0f}, H={size:.0f}, t=2, pos=({x:.0f},{y:.0f},0))  # {label}'

    if ctype == "sphere":
        r = size
        return f'{prim}("{name}", r={r:.0f}, pos=({x:.0f},{y:.0f},0))  # {label}: 半径{r:.0f}'

    if ctype == "cylinder":
        r = c.get("cylinderRadius", size / 2)
        h = size
        return f'{prim}("{name}", r={r:.0f}, h={h:.0f}, pos=({x:.0f},{y:.0f},0))  # {label}: r={r:.0f}, h={h:.0f}'

    if ctype in ("cone", "pyramid"):
        r = size * 0.35
        h = size * 0.8
        return f'revolved_solid("{name}", profile_points=[(0,0),({r:.0f},0),(0,{h:.0f})], axis_start=(0,0,0), axis_end=(0,1,0), angle_deg=360, pos=({x:.0f},{y:.0f},0))  # {label}'

    if ctype == "circle":
        r = size / 2
        return f'cylinder("{name}", r={r:.0f}, h=3, pos=({x:.0f},{y:.0f},0))  # 圆形薄片: r={r:.0f}'

    if ctype in ("triangle", "diamond", "pentagon", "hexagon"):
        r = size / 2
        n = {"triangle": 3, "diamond": 4, "pentagon": 5, "hexagon": 6}[ctype]
        pts = [(round(r * math.cos(2 * math.pi * i / n - math.pi / 2), 1),
                round(r * math.sin(2 * math.pi * i / n - math.pi / 2), 1)) for i in range(n)]
        pts_str = ", ".join(f"({px},{py})" for px, py in pts)
        return f'extruded_profile("{name}", profile_points=[{pts_str}], height=5, pos=({x:.0f},{y:.0f},0))  # {label}'

    return None


# === 场景 → FreeCAD 可执行模型 ===

def scene_to_parts(scene: dict) -> list:
    """将 scene JSON 的 components 转为 generate_model() 的 parts 参数。

    调度各 category router 的 component_to_part。
    """
    from .routers import component_to_part

    components = scene.get("components", [])
    parts = []
    for idx, c in enumerate(components):
        part = component_to_part(c, idx + 1)
        if part:
            parts.append(part)
    return parts


def scene_to_model_code(scene: dict, output_name: str = "SketchDesign") -> str:
    """把 scene JSON 直接转成可执行的 FreeCAD Python 代码。

    不需要 AI agent 介入——直接调用 generate_model_export()。
    """
    from anvil.tools.primitives import generate_model_export
    parts = scene_to_parts(scene)
    if not parts:
        return ""
    return generate_model_export(parts, [], output_name, step_path="/tmp/output.step")
