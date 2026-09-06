"""Anvil 共享依赖 — 供 web.py 和 routers/ 共同使用。"""
import os
import threading
from collections import OrderedDict
from pathlib import Path
from .project.manager import resolve_project_dir  # 保留:project/manager 内部及旧路由可能引用

# 数据目录与源码分离:ANVIL_DATA_DIR 环境变量指定数据根(projects/output/tmp/anvil.db 等),
# 默认 <Anvil>/data。源码目录(anvil/ 包)不含任何运行时数据。
DATA_DIR = os.environ.get("ANVIL_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
# 兼容:根级 projects(旧);用户目录为 projects/<username>/
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

# A3:agents LRU 缓存 — 有界,防内存膨胀。
# agent 状态外置(.model_state.json/.anvil_history.jsonl/决策记录),
# 淘汰无损:重建时自动恢复(见 agent._restore_history)。
AGENTS_MAX = int(os.environ.get("ANVIL_AGENTS_MAX", "20"))
_agents_lock = threading.Lock()
_agents: OrderedDict = OrderedDict()


class _AgentLRU:
    """线程安全 LRU:读写都移到队尾;超限淘汰队首。"""

    def __init__(self, maxsize):
        self.maxsize = maxsize

    def get(self, key):
        with _agents_lock:
            if key in _agents:
                _agents.move_to_end(key)
                return _agents[key]
            return None

    def put(self, key, agent):
        with _agents_lock:
            _agents[key] = agent
            _agents.move_to_end(key)
            while len(_agents) > self.maxsize:
                _agents.popitem(last=False)  # 淘汰最久未用

    def remove(self, key):
        with _agents_lock:
            _agents.pop(key, None)

    def keys(self):
        with _agents_lock:
            return list(_agents.keys())


agents = _AgentLRU(AGENTS_MAX)


def user_projects_dir(username: str) -> str:
    """每个用户一个项目根目录:data/projects/<username>/。登录后自动导航到自己的目录。"""
    name = (username or "default").strip() or "default"
    d = os.path.join(PROJECTS_DIR, name)
    os.makedirs(d, exist_ok=True)
    return d


# 共享权限级别(从低到高)
PERM_READ = "read"
PERM_COMMENT = "comment"
PERM_EDIT = "edit"
_PERM_RANK = {PERM_READ: 1, PERM_COMMENT: 2, PERM_EDIT: 3}


def _user_id_by_name(username: str):
    try:
        from anvil.db import SessionLocal, User as DBUser
        db = SessionLocal()
        try:
            u = db.query(DBUser).filter_by(username=username or "default").first()
            return u.id if u else None
        finally:
            db.close()
    except Exception:
        return None


def resolve_project_access(project_ref: str, username: str):
    """解析项目访问,返回 (project_dir, permission, is_owner)。

    全走 DB projects 表,不再扫描文件系统(用户决策 2026-09-03)。
    project_ref 匹配:path 末尾段 = project_ref,或 id = project_ref。
    权限:自己的项目(user_id 匹配)→ edit;admin → read 看全部;
          shares 表 → 对应权限。
    """
    from anvil.db import SessionLocal, ProjectDB as PDB, User, Share
    uid = _user_id_by_name(username)
    db = SessionLocal()
    try:
        ref = str(project_ref).strip("/")
        # 身份统一 bigint:优先按 projects.id 匹配;旧 hash/中文链接按 path 末段兼容
        row = None
        if ref.isdigit():
            row = db.query(PDB).filter_by(id=int(ref)).first()
        if row is None:
            row = db.query(PDB).filter(PDB.path.like("%/" + ref)).first()
        if row is None:
            return None, None, False
        # 权限判定
        me = db.query(User).filter_by(username=username).first()
        is_owner = bool(me and row.user_id == me.id)
        if is_owner:
            return row.path, PERM_EDIT, True
        if me and me.role == "admin":
            return row.path, PERM_READ, False  # 超管可看全部项目
        # 共享项目(shares.project_id 为 bigint;del_flag=0 有效授权)
        if uid is not None:
            sh = db.query(Share).filter_by(
                project_id=row.id, target_id=uid, del_flag="0").first()
            if sh:
                return row.path, sh.permission, False
        return None, None, False
    finally:
        db.close()


def get_agent(project_ref, username: str = "default"):
    """Get or create agent for a project (scoped to user's projects dir, 支持共享项目)。

    project_ref can be a project_id (new format) or dir_name (old format).
    """
    from anvil.agent import DesignAgent
    key = (username or "default") + ":" + str(project_ref)
    agent = agents.get(key)
    if agent is None:
        # 共享项目也解析(先自己目录,再 shares)
        project_dir, _perm, _own = resolve_project_access(project_ref, username)
        if project_dir is None:
            return None
        # 查用户 id(模型配置按 user_id 存)
        user_id = None
        try:
            from anvil.db import SessionLocal, User as DBUser
            db = SessionLocal()
            try:
                u = db.query(DBUser).filter_by(username=username or "default").first()
                user_id = u.id if u else None
            finally:
                db.close()
        except Exception:
            pass
        agent = DesignAgent(project_dir, user_id=user_id)
        agents.put(key, agent)
    return agent


def clear_agent(project_ref, username: str = "default"):
    key = (username or "default") + ":" + str(project_ref)
    agents.remove(key)
