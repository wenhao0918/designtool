"""
Template engine — selects and injects design-context prompts.

Keeps the base system prompt universal. Problem-specific guidance
is loaded from templates/ directory based on design type.
"""

import os
import glob
import re

TEMPLATES_DIR = os.path.dirname(os.path.abspath(__file__))


_templates_cache = None


def _load_templates():
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache

    templates = {}
    pattern = os.path.join(TEMPLATES_DIR, "*.md")
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath) as f:
            content = f.read()
        name = os.path.splitext(os.path.basename(fpath))[0]

        # Parse front matter (### Triggers: ...)
        triggers = []
        desc = ""
        for line in content.split("\n"):
            if line.startswith("Triggers:"):
                triggers = [t.strip().lower() for t in line[9:].split(",")]
            elif line.startswith("Description:"):
                desc = line[12:].strip()

        templates[name] = {
            "content": content,
            "triggers": triggers,
            "description": desc,
        }
    _templates_cache = templates
    return templates


def match_template(requirement_text):
    """Find the best matching template for a design requirement.

    Args:
        requirement_text: user's design description

    Returns:
        dict with template name, content, confidence, or None
    """
    templates = _load_templates()
    text_lower = requirement_text.lower()

    best = None
    best_score = 0

    for name, tmpl in templates.items():
        score = 0
        for trigger in tmpl["triggers"]:
            if trigger in text_lower:
                score += 1
        if score > best_score:
            best_score = score
            best = name

    if best and best_score > 0:
        t = templates[best]
        return {
            "template": best,
            "description": t["description"],
            "content": t["content"],
            "confidence": "%.0f%%" % (best_score / max(len(t["triggers"]), 1) * 100),
            "match_score": best_score,
        }
    return None


def list_templates():
    """List all available templates with descriptions."""
    templates = _load_templates()
    return {k: {"name": k, "description": v["description"],
                 "triggers": v["triggers"]}
            for k, v in templates.items()}


# Tool definition for Anvil agent

def tool_def():
    return {
        "type": "function",
        "function": {
            "name": "select_design_template",
            "description": "根据设计需求描述，选择最匹配的设计模版。模版提供专项设计指导、工具推荐和注意事项。请在 parse_requirement 后调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "用户的设计需求描述"
                    }
                },
                "required": ["requirement"]
            }
        }
    }


def tool_list_def():
    return {
        "type": "function",
        "function": {
            "name": "list_design_templates",
            "description": "列出所有可用的设计模版及其适用场景。",
            "parameters": {"type": "object", "properties": {}}
        }
    }
