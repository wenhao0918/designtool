"""
Design workshop — collaborative brainstorming + synthesis.

Flow: open session → collect ideas from anyone → AI synthesizes → design brief
"""

import os
import json
import re
from datetime import datetime


IDEA_CATEGORIES = ["功能", "结构", "尺寸", "材料", "驱动", "外观", "成本", "工艺", "其他"]


class WorkshopManager:
    """Open-ended design brainstorming sessions."""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.dir = os.path.join(project_dir, "workshops")
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, sid):
        return os.path.join(self.dir, "%s.json" % sid)

    def open(self, topic, description=""):
        """Open a new brainstorming session.

        Args:
            topic: design topic, e.g. "坐便器设计"
            description: context or problem statement
        """
        sid = "WS_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
        session = {
            "id": sid,
            "topic": topic,
            "description": description,
            "status": "collecting",
            "ideas": [],
            "synthesis": None,
            "design_brief": None,
            "opened_at": datetime.now().isoformat(),
            "closed_at": None,
        }
        self._save(session)
        return session

    def _save(self, session):
        with open(self._path(session["id"]), "w") as f:
            json.dump(session, f, indent=2, ensure_ascii=False)

    def get(self, sid):
        path = self._path(sid)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return None

    def list(self, limit=10):
        files = sorted(
            [f for f in os.listdir(self.dir) if f.endswith(".json")],
            reverse=True,
        )[:limit]
        result = []
        for fname in files:
            with open(os.path.join(self.dir, fname)) as f:
                d = json.load(f)
            result.append({
                "id": d["id"],
                "topic": d.get("topic", ""),
                "status": d["status"],
                "idea_count": len(d.get("ideas", [])),
                "opened_at": d["opened_at"],
            })
        return result

    def contribute(self, sid, author, content, category=None):
        """Add an idea to the session.

        Args:
            sid: session ID
            author: who contributed
            content: the idea text
            category: optional category hint
        """
        session = self.get(sid)
        if not session:
            return {"error": "Session not found"}
        if session["status"] != "collecting":
            return {"error": "Session is closed for contributions"}

        if not category:
            category = self._auto_categorize(content)

        idea = {
            "id": "idea_%d" % (len(session.get("ideas", [])) + 1),
            "author": author,
            "content": content,
            "category": category,
            "timestamp": datetime.now().isoformat(),
        }
        session.setdefault("ideas", []).append(idea)
        self._save(session)
        return session

    def _auto_categorize(self, text):
        """Simple keyword-based categorization."""
        text_lower = text.lower()
        for cat, keywords in [
            ("功能", ["功能", "使用", "操作", "用户", "坐", "站", "躺", "清洗"]),
            ("结构", ["结构", "铰链", "连接", "固定", "支撑", "框架", "底座"]),
            ("尺寸", ["尺寸", "长", "宽", "高", "mm", "厚", "壁厚"]),
            ("材料", ["材料", "不锈钢", "塑料", "陶瓷", "铝合金", "钢"]),
            ("驱动", ["驱动", "电机", "推杆", "电动", "气缸", "丝杆"]),
            ("外观", ["外观", "美观", "颜色", "造型", "圆角"]),
            ("成本", ["成本", "价格", "预算", "省钱"]),
            ("工艺", ["工艺", "制造", "冲压", "注塑", "焊接", "装配"]),
        ]:
            for kw in keywords:
                if kw in text_lower:
                    return cat
        return "其他"

    def synthesize(self, sid):
        """Synthesize all ideas into a structured design brief.

        Groups ideas by category, extracts key decisions,
        generates a design brief that Anvil can use.
        """
        session = self.get(sid)
        if not session:
            return {"error": "Session not found"}

        ideas = session.get("ideas", [])
        if not ideas:
            return {"error": "No ideas to synthesize"}

        # Group by category
        grouped = {}
        for idea in ideas:
            cat = idea.get("category", "其他")
            grouped.setdefault(cat, []).append(idea["content"])

        # Build synthesis
        synthesis = {
            "total_ideas": len(ideas),
            "participants": list(set(i["author"] for i in ideas)),
            "categories": list(grouped.keys()),
            "groups": {},
        }
        for cat, items in grouped.items():
            synthesis["groups"][cat] = {
                "count": len(items),
                "ideas": items,
            }

        # Generate design brief
        brief_lines = []
        brief_lines.append("# 设计简报: %s" % session.get("topic", ""))
        brief_lines.append("")
        brief_lines.append("## 背景")
        brief_lines.append(session.get("description", ""))
        brief_lines.append("")
        brief_lines.append("## 需求汇总")
        for cat, items in grouped.items():
            brief_lines.append("")
            brief_lines.append("### %s（%d条）" % (cat, len(items)))
            for content in items:
                brief_lines.append("- %s" % content)

        design_brief = "\n".join(brief_lines)

        session["status"] = "synthesized"
        session["synthesis"] = synthesis
        session["design_brief"] = design_brief
        session["closed_at"] = datetime.now().isoformat()
        self._save(session)

        return {"synthesis": synthesis, "design_brief": design_brief, "session_id": sid}


# ===== Tool definitions =====

def tool_workshop_open():
    return {
        "type": "function",
        "function": {
            "name": "workshop_open",
            "description": "开启一个设计头脑风暴工作坊。设定主题和背景，任何人都可以贡献想法。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "设计主题，如 坐便器设计"},
                    "description": {"type": "string", "description": "背景描述或问题陈述"}
                },
                "required": ["topic"]
            }
        }
    }


def tool_workshop_contribute():
    return {
        "type": "function",
        "function": {
            "name": "workshop_contribute",
            "description": "在工作坊中贡献一个想法。任何参与人都可以调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "author": {"type": "string", "description": "贡献人姓名/角色"},
                    "content": {"type": "string", "description": "想法内容"},
                    "category": {"type": "string", "description": "分类: 功能/结构/尺寸/材料/驱动/外观/成本/工艺/其他"}
                },
                "required": ["session_id", "author", "content"]
            }
        }
    }


def tool_workshop_synthesize():
    return {
        "type": "function",
        "function": {
            "name": "workshop_synthesize",
            "description": "汇总工作坊所有想法，按分类整理，生成设计简报。简报可直接作为 Anvil 的设计输入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"}
                },
                "required": ["session_id"]
            }
        }
    }


ALL_WORKSHOP_TOOLS = [
    tool_workshop_open(),
    tool_workshop_contribute(),
    tool_workshop_synthesize(),
]
