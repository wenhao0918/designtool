"""
Requirement parser — extracts structured design spec from natural language.

Uses a dedicated LLM call with a focused extraction prompt.
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

_PARSE_PROMPT = """你是一个机械设计需求分析师。你的任务是将用户的设计需求解析为结构化参数。

从以下描述中提取所有设计要素。如果描述中没有明确给出某个参数，用 null 标记。

重点关注：
1. 零件: 有哪些零件/部件？名字、功能、大致尺寸
2. 连接/关节: 零件之间如何连接？铰链、焊接、螺栓？位置在哪？
3. 密封: 有没有密封要求？什么类型、位置、材料？
4. 约束: 空心？敞口？有底？有壁？材料要求？受力情况？
5. 运动: 有没有相对运动？运动范围？驱动方式？

只输出 JSON，不要其他文字。

JSON schema:
{
  "parts": [
    {
      "name": "零件名（如后部、前部）",
      "function": "功能描述",
      "approx_size": {"l": null, "w": null, "h": null}
    }
  ],
  "joints": [
    {
      "type": "铰链/焊接/螺栓...",
      "position": "上平面/底部/侧面/...",
      "connects": ["零件A", "零件B"],
      "axis": "x/y/z/null",
      "details": "额外描述"
    }
  ],
  "seals": [
    {
      "type": "波纹管/O型圈/垫片/...",
      "material": "金属/橡胶/...",
      "location": "之间/内部/...",
      "connects": ["零件A", "零件B"]
    }
  ],
  "constraints": {
    "hollow": true/false,
    "open_top": true/false,
    "has_bottom": true/false,
    "has_walls": true/false,
    "material": null,
    "load_N": null,
    "num_parts": null
  },
  "motion": {
    "type": null,
    "range_deg": null,
    "axis": null,
    "drive_type": null
  },
  "uncertainties": ["未明确的信息项1", "未明确的信息项2"]
}
"""


def _call_llm(user_text, base_url, api_key, model):
    """Internal LLM call for parsing."""
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _PARSE_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning("LLM parse failed: %s", e)
        return json.dumps({
            "parts": [],
            "joints": [],
            "seals": [],
            "constraints": {"hollow": None, "open_top": None, "has_bottom": None, "has_walls": None},
            "motion": {},
            "uncertainties": ["Failed to parse: " + str(e)],
        })


def parse_requirement(text: str, user_id=None) -> dict:
    """Parse natural language design requirement into structured spec.

    Uses configured LLM (用户自配优先,策略同 llm._get_config).
    Falls back to basic heuristic parsing if LLM unavailable.

    Args:
        text: user's design description
        user_id: 发起用户 id(模型配置策略按用户走)

    Returns:
        dict with parts, joints, seals, constraints, motion, uncertainties
    """
    try:
        from .llm import _get_config, ModelNotConfigured
        base_url, api_key, model = _get_config("text", user_id=user_id)
    except ModelNotConfigured:
        return _heuristic_parse(text)
    except Exception:
        base_url = os.environ.get("ANVIL_LLM_BASE_URL", "").rstrip("/")
        api_key = os.environ.get("ANVIL_LLM_API_KEY", "")
        model = os.environ.get("ANVIL_MODEL", "glm-4.5-flash")

    if base_url and api_key:
        try:
            result = _call_llm(text, base_url, api_key, model)
            data = json.loads(result)
            return data
        except Exception as e:
            logger.error("Requirement parser LLM error: %s", e)
            return _heuristic_parse(text)
    else:
        return _heuristic_parse(text)


def _heuristic_parse(text: str) -> dict:
    """Basic keyword-based parse when LLM is unavailable."""
    spec = {
        "parts": [],
        "joints": [],
        "seals": [],
        "constraints": {"hollow": False, "open_top": False, "has_bottom": False, "has_walls": False},
        "motion": {},
        "uncertainties": [],
    }

    text_lower = text.lower()

    # Parts detection
    if "后" in text or "rear" in text_lower:
        spec["parts"].append({"name": "后部", "function": "臀部坐区", "approx_size": {"l": None, "w": None, "h": None}})
    if "前" in text or "front" in text_lower:
        spec["parts"].append({"name": "前部", "function": "双腿平置区", "approx_size": {"l": None, "w": None, "h": None}})

    # Joints
    if "铰链" in text or "hinge" in text_lower:
        joint = {"type": "铰链", "position": None, "connects": [], "axis": None}
        if "上平面" in text:
            joint["position"] = "上平面"
        spec["joints"].append(joint)

    # Seals
    if "波纹管" in text or "bellows" in text_lower:
        seal = {"type": "波纹管", "material": "金属", "location": "之间", "connects": []}
        spec["seals"].append(seal)

    # Constraints
    if "掏空" in text or "空心" in text or "hollow" in text_lower:
        spec["constraints"]["hollow"] = True
    if "无顶" in text or "open" in text_lower:
        spec["constraints"]["open_top"] = True
    if "有底" in text or "bottom" in text_lower:
        spec["constraints"]["has_bottom"] = True
    if "有壁" in text or "wall" in text_lower:
        spec["constraints"]["has_walls"] = True

    # Count parts
    if spec["parts"]:
        spec["constraints"]["num_parts"] = len(spec["parts"])

    if not spec["parts"]:
        spec["uncertainties"].append("未识别到明确的零件")
    if not spec["joints"]:
        spec["uncertainties"].append("未识别到连接方式")
    if not text.strip():
        spec["uncertainties"].append("需求描述为空")

    return spec


def to_tool_definition():
    return {
        "type": "function",
        "function": {
            "name": "parse_requirement",
            "description": "Parse natural language design requirement into structured specification. "
                          "Call this FIRST to extract parts, joints, seals, and constraints from user input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The user's design requirement description"
                    }
                },
                "required": ["text"]
            }
        }
    }
