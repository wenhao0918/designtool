"""Project manager — 项目工作区目录助手 + DB 元信息。

项目信息(名称/阶段/描述/归属/身份)全部在 DB projects 表,身份 = projects.id(bigint)。
本类只管:
  - 工作区目录结构(cad/docs/exports/knowledge 等,设计产物落盘处)
  - 从 DB 读项目元信息(get_config / name / phase)
  - 结构化设计日志追加(写 DB design_log_rows)

不再读写 .design/project.json / .anvil.json —— 文件元信息机制已删除(2026-09-04),
避免"文件身份"与"DB 身份"双数据源歧义。CAD 产物等二进制仍落工作区目录。
"""

import os
import re
import json
import uuid
from datetime import datetime


def _make_step_id(action):
    """Generate a unique step ID: action prefix + timestamp + random."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rnd = uuid.uuid4().hex[:6]
    return f"{action}_{ts}_{rnd}"


class ProjectManager:
    """Manage an Anvil project workspace directory (metadata lives in DB)."""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self._pid = None

    # ---------- 工作区初始化 ----------

    @classmethod
    def init_workspace(cls, project_dir):
        """建好工作区子目录(cad/docs/...),不写任何元信息文件。返回 manager。"""
        os.makedirs(project_dir, exist_ok=True)
        for subdir in ["cad", "docs/notes", "docs/decisions", "docs/calculations",
                       "docs/changelog", "exports", "knowledge"]:
            os.makedirs(os.path.join(project_dir, subdir), exist_ok=True)
        return cls(project_dir)

    @classmethod
    def create(cls, projects_base, name, description=""):
        """[CLI 兼容] 仅初始化工作区目录;正式建项目请走 web.create_project(DB 注册)。

        目录名用 name 的安全形式;返回 (manager, dir_name)。不写 project.json/.anvil.json。
        """
        dir_name = re.sub(r"[^\w\-]", "_", name)[:32] or uuid.uuid4().hex[:12]
        project_dir = os.path.join(projects_base, dir_name)
        os.makedirs(project_dir, exist_ok=False)
        mgr = cls.init_workspace(project_dir)
        return mgr, dir_name

    # ---------- 身份 / 元信息(走 DB) ----------

    @property
    def pid(self):
        """projects.id(bigint),通过 projects.path 反查。"""
        if self._pid is None:
            from ..history_db import _pid as _dir_to_pid
            self._pid = _dir_to_pid(self.project_dir)
        return self._pid

    def _db_row(self):
        from ..db import SessionLocal, ProjectDB
        with SessionLocal() as s:
            return s.query(ProjectDB).filter_by(id=self.pid).first()

    def get_project_id(self):
        return self.pid

    def get_config(self):
        """项目元信息(来自 DB projects 行)。兼容旧调用方的字段名。"""
        row = self._db_row()
        return {
            "project_id": self.pid,
            "name": (row.name if row else "") or "未命名",
            "phase": (row.phase if row else "concept") or "concept",
            "description": (row.description if row and row.description else "")
                           or (row.display_name if row else "") or "",
            "max_iterations": 50,
        }

    def set_stage(self, stage):
        from ..db import SessionLocal, ProjectDB
        with SessionLocal() as s:
            row = s.query(ProjectDB).filter_by(id=self.pid).first()
            if row:
                row.phase = stage
                s.commit()

    def get_stage(self):
        return self.get_config().get("phase", "concept")

    # ---------- 设计日志(结构化五要素,写 DB design_log_rows) ----------

    def append_log(self, entry):
        """追加一条结构化设计日志到 DB。

        schema(五要素 + 可选快照):
          id / time / action / instruction / llm_response /
          output_dir / result_log / project_id(bigint) /
          q_snapshot(可选:重置事件的 Q 全需求矩阵快照 blob)
        """
        entry.setdefault("id", _make_step_id(entry.get("action", "unknown")))
        entry.setdefault("time", datetime.now().isoformat())
        entry["project_id"] = self.pid
        entry.setdefault("instruction", "")
        entry.setdefault("llm_response", "")
        entry.setdefault("output_dir", "")
        entry.setdefault("result_log", {})
        if not isinstance(entry["result_log"], dict):
            entry["result_log"] = {"summary": str(entry["result_log"])}
        if not isinstance(entry["instruction"], str):
            entry["instruction"] = str(entry["instruction"])
        from .. import history_db
        history_db.db_append_design_log(self.project_dir, entry)

    # ---------- CAD 产物列举(工作区;跳过 _archive 归档目录) ----------

    @staticmethod
    def _is_cad(fn):
        return fn.endswith((".FCStd", ".step", ".stp", ".stl"))

    def list_cad_files(self):
        cad_dir = os.path.join(self.project_dir, "cad")
        if not os.path.exists(cad_dir):
            return []
        files = []
        for entry in os.listdir(cad_dir):
            if entry.startswith("_"):  # _archive 等归档目录不算当前产物
                continue
            entry_path = os.path.join(cad_dir, entry)
            if os.path.isdir(entry_path):
                for f in os.listdir(entry_path):
                    if self._is_cad(f):
                        files.append(f)
            elif self._is_cad(entry):
                files.append(entry)
        return files

    def list_cad_files_full(self):
        """List CAD files (flat + version subdirs), skipping _archive."""
        cad_dir = os.path.join(self.project_dir, "cad")
        if not os.path.exists(cad_dir):
            return []
        result = []

        def _sort_key(entry):
            m = re.search(r"_(\d{8})_(\d{6})_(\d{3})$", entry)
            return m.group(0) if m else entry

        for entry in sorted(os.listdir(cad_dir), key=_sort_key):
            if entry.startswith("_"):  # 跳过 _archive 归档
                continue
            entry_path = os.path.join(cad_dir, entry)
            if os.path.isdir(entry_path):
                for f in sorted(os.listdir(entry_path)):
                    if self._is_cad(f):
                        result.append(os.path.join(entry, f))
            elif self._is_cad(entry):
                result.append(entry)
        return result


def resolve_project_dir(projects_base, project_ref):
    """按项目引用定位工作区目录(走 DB projects.path,不扫文件系统)。

    project_ref: projects.id(bigint / 数字串) 或 旧目录 hash/中文名(按 path 末段匹配)。
    projects_base 参数保留兼容签名,新模型忽略(目录以 DB path 为准)。

    Returns: (dir_path, project_id_str) 或 (None, None)。
    """
    from ..db import SessionLocal, ProjectDB
    ref = str(project_ref).strip("/")
    with SessionLocal() as s:
        row = None
        if ref.isdigit():
            row = s.query(ProjectDB).filter_by(id=int(ref)).first()
        if row is None:
            row = s.query(ProjectDB).filter(ProjectDB.path.like("%/" + ref)).first()
        if row is not None and os.path.isdir(row.path):
            return row.path, str(row.id)
    return None, None
