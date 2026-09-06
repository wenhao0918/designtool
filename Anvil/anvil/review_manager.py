"""
Review manager — design review workflow.

Flow: submit → (AI or human) adds items → Anvil responds → fix → close
"""

import os
import json
import copy
from datetime import datetime


class ReviewManager:
    """Manages design reviews for a project."""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.reviews_dir = os.path.join(project_dir, "reviews")
        os.makedirs(self.reviews_dir, exist_ok=True)

    def _path(self, rid):
        return os.path.join(self.reviews_dir, "%s.json" % rid)

    def _next_id(self):
        existing = [f for f in os.listdir(self.reviews_dir) if f.endswith(".json")]
        n = len(existing) + 1
        return "REV%03d" % n

    def submit(self, label=""):
        """Submit current design for review.

        Captures the current model state as a snapshot.
        Returns review dict.
        """
        rid = self._next_id()
        ts = datetime.now().isoformat()
        # Snapshot model state if available
        model_path = os.path.join(self.project_dir, ".model_state.json")
        model_snapshot = None
        if os.path.exists(model_path):
            with open(model_path) as f:
                model_snapshot = json.load(f)

        review = {
            "id": rid,
            "label": label,
            "status": "open",
            "submitted_at": ts,
            "updated_at": ts,
            "model_snapshot": model_snapshot,
            "items": [],
        }
        with open(self._path(rid), "w") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)
        return review

    def get(self, rid):
        """Get review by ID or latest."""
        if rid:
            path = self._path(rid)
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
            return None
        # Return latest
        return self.list(limit=1)[0] if self.list() else None

    def list(self, limit=20):
        """List reviews sorted by time descending."""
        files = sorted(
            [f for f in os.listdir(self.reviews_dir) if f.endswith(".json")],
            reverse=True,
        )[:limit]
        result = []
        for f in files:
            with open(os.path.join(self.reviews_dir, f)) as fp:
                data = json.load(fp)
            result.append({
                "id": data["id"],
                "label": data.get("label", ""),
                "status": data["status"],
                "submitted_at": data["submitted_at"],
                "item_count": len(data.get("items", [])),
                "pending_count": len([i for i in data.get("items", []) if i.get("status") == "pending"]),
            })
        return result

    def add_item(self, rid, severity, category, component, title, description, suggestion, created_by="reviewer"):
        """Add a review item (feedback point).

        Args:
            rid: review ID
            severity: 严重 / 一般 / 建议
            category: 结构 / 尺寸 / 材料 / 驱动 / 装配 / 其他
            component: which part/feature the feedback targets
            title: short summary
            description: detailed explanation
            suggestion: suggested fix
            created_by: identifier of the reviewer

        Returns updated review.
        """
        review = self.get(rid)
        if not review:
            return {"error": "Review not found"}
        item_id = "item_%d" % (len(review.get("items", [])) + 1)
        item = {
            "id": item_id,
            "severity": severity,
            "category": category,
            "component": component,
            "title": title,
            "description": description,
            "suggestion": suggestion,
            "status": "pending",
            "response": "",
            "created_by": created_by,
            "created_at": datetime.now().isoformat(),
        }
        review.setdefault("items", []).append(item)
        review["updated_at"] = datetime.now().isoformat()
        with open(self._path(rid), "w") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)
        return review

    def respond_to_item(self, rid, item_id, response, accept=True):
        """Anvil responds to a review item.

        Args:
            rid: review ID
            item_id: item ID
            response: Anvil's response text
            accept: True = accepted and will fix, False = rejected with reason
        """
        review = self.get(rid)
        if not review:
            return {"error": "Review not found"}
        for item in review.get("items", []):
            if item["id"] == item_id:
                item["status"] = "accepted" if accept else "rejected"
                item["response"] = response
                item["responded_at"] = datetime.now().isoformat()
                break
        review["updated_at"] = datetime.now().isoformat()
        # Auto-close if all items responded
        all_responded = all(i.get("status") in ("accepted", "rejected") for i in review.get("items", []))
        if all_responded and review.get("items"):
            review["status"] = "closed"
        with open(self._path(rid), "w") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)
        return review

    def close(self, rid):
        """Manually close a review."""
        review = self.get(rid)
        if review:
            review["status"] = "closed"
            review["updated_at"] = datetime.now().isoformat()
            with open(self._path(rid), "w") as f:
                json.dump(review, f, indent=2, ensure_ascii=False)
        return review


# ===== Tool definitions for agent =====

def tool_submit_review():
    return {
        "type": "function",
        "function": {
            "name": "design_submit_review",
            "description": "提交当前设计给审核员评审。会保存当前模型状态的快照。",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "审核标签，如 '初版审核'"}
                }
            }
        }
    }


def tool_list_reviews():
    return {
        "type": "function",
        "function": {
            "name": "design_list_reviews",
            "description": "列出所有审核记录及其状态。",
            "parameters": {"type": "object", "properties": {}}
        }
    }


def tool_get_review():
    return {
        "type": "function",
        "function": {
            "name": "design_get_review",
            "description": "获取某次审核的详细内容，包括所有审核意见。",
            "parameters": {
                "type": "object",
                "properties": {
                    "review_id": {"type": "string", "description": "审核ID，不传则查最新"}
                }
            }
        }
    }


def tool_respond_item():
    return {
        "type": "function",
        "function": {
            "name": "design_respond_item",
            "description": "回复一条审核意见。接受或拒绝，并说明理由。",
            "parameters": {
                "type": "object",
                "properties": {
                    "review_id": {"type": "string"},
                    "item_id": {"type": "string"},
                    "response": {"type": "string", "description": "回复内容，如已接受则说明修改方案"},
                    "accept": {"type": "boolean", "description": "是否接受此意见"}
                },
                "required": ["review_id", "item_id", "response"]
            }
        }
    }


ALL_REVIEW_TOOLS = [
    tool_submit_review(),
    tool_list_reviews(),
    tool_get_review(),
    tool_respond_item(),
]
