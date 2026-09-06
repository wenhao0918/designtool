"""SketchService — 绘图识别核心模块。

流程: PNG + 场景描述 → vision 模型 → 设计意图 JSON
"""

import json
import os
import sys

# Anvil 与 SketchService 同在 DesignTool/ 下，共享 Python 环境
_root = os.path.dirname(os.path.abspath(__file__))
_anvil_path = os.path.join(_root, '..', 'Anvil')
if _anvil_path not in sys.path:
    sys.path.insert(0, _anvil_path)

from anvil.llm import chat_vision


SKETCH_PROMPT = """你是机械设计工程师，正在解读工程师的手绘概念草图。请仔细识别图片内容，结合附带的场景描述，输出结构化的设计需求。

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


def recognize_sketch(image_bytes: bytes, scene_text: str = "") -> dict:
    """识别手绘草图，返回设计意图 dict。"""
    import base64

    try:
        b64 = base64.b64encode(image_bytes).decode()
        prompt = SKETCH_PROMPT
        if scene_text:
            prompt = scene_text + "\n\n" + SKETCH_PROMPT

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ]
        resp = chat_vision(messages, temperature=0.2)
        content = resp.choices[0].message.content.strip()

        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
        return json.loads(content)
    except json.JSONDecodeError as e:
        return {"error": f"识别结果解析失败: {e}"}
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

    return (
        f"【手绘草图识别结果】\n"
        f"零件类型: {intent.get('type', '未知')}\n"
        f"尺寸: {dim_str}\n"
        f"结构特征: {feat_str}\n"
        f"设计意图: {desc}\n"
        f"建议零件名: {intent.get('suggested_name', 'part')}\n\n"
        f"请根据以上设计意图进行参数化建模。"
    )
