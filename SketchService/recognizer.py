"""sketch-service — 通用图片语义解读微服务

本质: 图 + 用户提示词 → AI 按提示词解读 → 结构化结果
不预设领域: 涂鸦/漫画/数学/机械/电路...由用户提示词决定"画的是什么、如何解读"

配置: 模型配置与 Anvil 共用命名规范（推理/vision 分开）：
  ANVIL_LLM_*     推理模型（可选，预留）
  ANVIL_VISION_*  vision 模型（必需，图片解读）
  SKETCH_CONFIG   可选，指向 config.json（profiles 机制，参考 Dao Code）
"""

import base64
import json
import os
from pathlib import Path

# === 配置解析 ===

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# 默认解读提示词（用户不传时使用）——通用，不预设领域
DEFAULT_PROMPT = """请仔细解读这张图片，理解它的内容和意图，然后输出结构化的描述。

输出格式（严格JSON，不要其他文字）：
{
  "summary": "图片内容的简要总结（1-2句话）",
  "elements": ["识别出的主要元素/对象列表"],
  "details": {"关键细节/属性": "值", ...},
  "intent": "可能的意图或用途推测"
}
"""


def _load_config() -> dict:
    """加载 profiles 配置。SKETCH_CONFIG 指定路径，否则用默认 config.json。"""
    path = os.environ.get("SKETCH_CONFIG", str(DEFAULT_CONFIG_PATH))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_vision_config() -> tuple:
    """返回 (base_url, api_key, model)。优先级：环境变量 > config.json profile。"""
    cfg = _load_config()
    profile_name = cfg.get("activeProfile", "vision")
    profile = cfg.get("profiles", {}).get(profile_name, {})

    base_url = (
        os.environ.get("ANVIL_VISION_BASE_URL")
        or profile.get("baseUrl")
        or ""
    )
    api_key = (
        os.environ.get("ANVIL_VISION_API_KEY")
        or profile.get("apiKey")
        or ""
    )
    model = (
        os.environ.get("ANVIL_VISION_MODEL")
        or profile.get("model")
        or "moonshot-v1-128k-vision-preview"
    )
    return base_url, api_key, model

def get_llm_config() -> tuple:
    """返回 (base_url, api_key, model)。推理模型，用于文本生成（可选）。"""
    cfg = _load_config()
    profile_name = cfg.get("activeProfile", "vision")
    profile = cfg.get("profiles", {}).get(profile_name, {})

    base_url = (
        os.environ.get("ANVIL_LLM_BASE_URL")
        or profile.get("llmBaseUrl")
        or ""
    )
    api_key = (
        os.environ.get("ANVIL_LLM_API_KEY")
        or profile.get("llmApiKey")
        or ""
    )
    model = (
        os.environ.get("ANVIL_MODEL")
        or profile.get("llmModel")
        or "moonshot-v1-128k-vision-preview"
    )
    return base_url, api_key, model


# === 解读 ===


def recognize_image(image_bytes: bytes, prompt: str = "") -> dict:
    """解读图片，返回结构化结果。

    Args:
        image_bytes: 图片原始字节（PNG/JPEG）
        prompt: 用户自定义提示词——决定"画的是什么、如何解读"。
                空则用 DEFAULT_PROMPT（通用解读）。

    Returns:
        dict: 结构化解读结果（格式由用户提示词决定）
    """
    base_url, api_key, model = get_vision_config()
    if not base_url or not api_key:
        return {"error": "Vision 模型未配置。请设置 ANVIL_VISION_BASE_URL / ANVIL_VISION_API_KEY / ANVIL_VISION_MODEL"}

    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=120)

    # 用户提示词优先，空则用默认
    effective_prompt = prompt.strip() if prompt and prompt.strip() else DEFAULT_PROMPT

    b64 = base64.b64encode(image_bytes).decode()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": effective_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        # 提取 JSON（容错 ``` 包裹）
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
        return json.loads(content)
    except json.JSONDecodeError as e:
        return {"error": f"解读结果解析失败: {e}", "raw": content if "content" in dir() else ""}
    except Exception as e:
        return {"error": f"视觉解读失败: {e}"}
