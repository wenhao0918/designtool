"""Design history — 对话流水(全部在 DB history_rows 表,2026-09-04 起)。

不再写 .anvil_history.jsonl(文件保存机制已删除)。project_id=projects.id(bigint),
由 history_db 经 projects.path 反查。DB 不可用直接抛错,不做文件兜底。
"""

from datetime import datetime


class DesignHistory:
    """Track design conversation and decisions (DB-backed)."""

    def __init__(self, project_dir: str):
        self.project_dir = project_dir

    def append(self, entry_type: str, content: dict):
        """追加一条流水。entry_type: user/assistant/tool/decision/change。"""
        from .. import history_db
        entry = {
            "type": entry_type,
            "timestamp": datetime.now().isoformat(),
            "data": content,
        }
        history_db.db_append_history(self.project_dir, entry)

    def get_all(self) -> list[dict]:
        """全部流水(按 seq 升序),元素含 type/timestamp/data。"""
        from .. import history_db
        return history_db.get_history_rows(self.project_dir)

    def get_recent(self, n: int = 10) -> list[dict]:
        return self.get_all()[-n:]

    def get_by_type(self, entry_type: str) -> list[dict]:
        return [e for e in self.get_all() if e.get("type") == entry_type]

    def get_summary(self) -> str:
        """Generate a summary of design history."""
        entries = self.get_all()
        if not entries:
            return "尚无设计记录。"

        summary = f"共 {len(entries)} 条记录\n"
        types = {}
        for e in entries:
            t = e.get("type", "?")
            types[t] = types.get(t, 0) + 1
        for t, count in types.items():
            summary += f"- {t}: {count} 条\n"

        last = entries[-1]
        summary += "\n最后操作: %s @ %s\n" % (
            last.get("type", "?"), str(last.get("timestamp", "?"))[:19])
        return summary
