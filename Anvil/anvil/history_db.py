"""历史/设计日志的数据库层 — 项目信息全部在 DB(2026-09-04 起)。

项目身份统一为 projects.id(bigint);不再有 .anvil_history.jsonl / .design/log
文件双写,也不做文件惰性迁移(文件保存机制已删除,避免双数据源歧义)。

表:
  history_rows(project_id bigint, seq, type, timestamp, data)      ← 对话流水
  design_log_rows(project_id bigint, seq, action, instruction, llm_response,
                  output_dir, result_log, q_snapshot, time, entry_id)  ← 设计日志
    q_snapshot: 重置事件携带的 Q 全需求矩阵快照 blob(JSON),用于回撤/分支
索引 (project_id, seq);data/result_log/q_snapshot 存 JSON 字符串(Text)。
DB 连不上直接报错(用户决策),不静默降级。
"""

import json
import os

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Index, BigInteger, DateTime

from .db import Base, SessionLocal

_tables_ready = False
_pid_cache = {}       # realpath(project_dir) → project_id(bigint)
_seq_cache = {}       # (table, project_id) → last_seq


def ensure_tables():
    global _tables_ready
    if _tables_ready:
        return
    Base.metadata.create_all(
        tables=[HistoryRow.__table__, DesignLogRow.__table__],
        bind=SessionLocal.kw["bind"])
    _tables_ready = True


class HistoryRow(Base):
    __tablename__ = "history_rows"
    id = Column(BigInteger().with_variant(Integer, "sqlite"),
                primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, nullable=False)   # FK→projects.id
    seq = Column(Integer, nullable=False)             # 1-based,项目内对话行号
    type = Column(String(16), nullable=False)         # user/assistant/tool
    timestamp = Column(String(40), default="")
    data = Column(Text)                               # JSON 字符串
    # ruoyi 审计(追加日志:只建不改,故仅 create 侧 + tenant;无 del_flag)
    tenant_id = Column(String(20), default="000000", index=True)
    create_dept = Column(BigInteger, nullable=True)
    create_by = Column(BigInteger, nullable=True)     # 商用时= sys_user.user_id
    create_time = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_hist_proj_seq", "project_id", "seq"),)


class DesignLogRow(Base):
    __tablename__ = "design_log_rows"
    id = Column(BigInteger().with_variant(Integer, "sqlite"),
                primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, nullable=False)   # FK→projects.id
    seq = Column(Integer, nullable=False)             # 日志行号(项目内递增)
    dltq_seq = Column(Integer, nullable=True)         # 指令序号 Δ#N(dltQ 账本 seq,永不复用;非译码轮为空)
    entry_id = Column(String(64), default="")
    action = Column(String(32), default="")
    instruction = Column(Text, default="")
    llm_response = Column(Text, default="")
    output_dir = Column(String(255), default="")
    result_log = Column(Text)                         # JSON 字符串
    q_snapshot = Column(Text)                         # Q 全需求矩阵快照 blob(重置事件)
    time = Column(String(40), default="")
    # ruoyi 审计(追加日志:只建不改,故仅 create 侧 + tenant;无 del_flag)
    tenant_id = Column(String(20), default="000000", index=True)
    create_dept = Column(BigInteger, nullable=True)
    create_by = Column(BigInteger, nullable=True)     # 商用时= sys_user.user_id
    create_time = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_dlog_proj_seq", "project_id", "seq"),)


# ---------- 内部工具 ----------

def _pid(project_dir):
    """项目目录 → projects.id(bigint)。通过 projects.path 反查(项目信息在 DB)。"""
    d = os.path.realpath(project_dir)
    if d not in _pid_cache:
        from .db import ProjectDB
        pid = None
        with SessionLocal() as s:
            # path 存绝对路径;用 realpath 末尾段 + 完整前缀双重兜底匹配
            row = s.query(ProjectDB).filter(ProjectDB.path == d).first()
            if row is None:
                base = os.path.basename(d.rstrip("/"))
                row = s.query(ProjectDB).filter(
                    ProjectDB.path.like("%/" + base)).first()
            pid = int(row.id) if row else None
        if pid is None:
            raise RuntimeError("项目未在 DB 注册,无法定位 project_id: %s" % d)
        _pid_cache[d] = pid
    return _pid_cache[d]


def _next_seq(session, model, pid):
    key = (model.__tablename__, pid)
    if key not in _seq_cache:
        from sqlalchemy import func
        v = session.query(func.max(model.seq)).filter_by(project_id=pid).scalar()
        _seq_cache[key] = int(v or 0)
    _seq_cache[key] += 1
    return _seq_cache[key]


# ---------- 写路径(只写 DB;DB 不可用直接抛错,不做文件兜底) ----------

def db_append_history(project_dir, entry, seq=None):
    """对话流水写 DB。project_id=projects.id(bigint)。失败直接抛错。"""
    ensure_tables()
    pid = _pid(project_dir)
    with SessionLocal() as s:
        if seq is None:
            seq = _next_seq(s, HistoryRow, pid)
        s.add(HistoryRow(project_id=pid, seq=seq, type=entry.get("type", ""),
                         timestamp=entry.get("timestamp", ""),
                         data=json.dumps(entry.get("data") or {},
                                         ensure_ascii=False)))
        s.commit()


def db_append_design_log(project_dir, entry):
    """设计日志写 DB。entry 可携带 q_snapshot(重置事件的 Q 全需求矩阵快照)。"""
    ensure_tables()
    pid = _pid(project_dir)
    qsnap = entry.get("q_snapshot")
    with SessionLocal() as s:
        seq = _next_seq(s, DesignLogRow, pid)
        s.add(DesignLogRow(
            project_id=pid, seq=seq,
            dltq_seq=(int(entry["dltq_seq"]) if entry.get("dltq_seq") is not None else None),
            entry_id=str(entry.get("id", "")),
            action=str(entry.get("action", "")),
            instruction=str(entry.get("instruction", "")),
            llm_response=str(entry.get("llm_response", "")),
            output_dir=str(entry.get("output_dir", "")),
            result_log=json.dumps(entry.get("result_log") or {},
                                  ensure_ascii=False),
            q_snapshot=(json.dumps(qsnap, ensure_ascii=False)
                        if qsnap is not None else None),
            time=str(entry.get("time", ""))))
        s.commit()


# ---------- 读路径(只走 DB;无文件兜底) ----------

def get_history_rows(project_dir):
    """全量对话流水(带 _seq),按 seq 升序。"""
    pid = _pid(project_dir)
    ensure_tables()
    with SessionLocal() as s:
        rows = (s.query(HistoryRow).filter_by(project_id=pid)
                .order_by(HistoryRow.seq).all())
        out = []
        for r in rows:
            try:
                data = json.loads(r.data or "{}")
            except Exception:
                data = {}
            out.append({"_seq": r.seq, "type": r.type,
                        "timestamp": r.timestamp, "data": data})
        return out


def get_recent_dialog(project_dir, n=2):
    """最近一轮问答(译码上下文用):[{role,content}]。

    欠约束提问后的补充轮,补充语单独看缺尺寸/对象——带上上一轮
    (原指令+【欠约束】问句)译码 LLM 才能拼出完整约束(2026-09-07)。
    只取一轮:更早轮次的回显文本会污染双通道输出格式。
    """
    try:
        rows = get_history_rows(project_dir)[-n:]
    except Exception:
        return []
    out = []
    for r in rows:
        c = (r.get("data") or {}).get("content") or ""
        if c:
            out.append({"role": r.get("type") or "user", "content": c[:300]})
    return out


def get_history_range(project_dir, from_seq, to_seq):
    pid = _pid(project_dir)
    ensure_tables()
    with SessionLocal() as s:
        rows = (s.query(HistoryRow)
                .filter(HistoryRow.project_id == pid,
                        HistoryRow.seq >= from_seq,
                        HistoryRow.seq <= to_seq)
                .order_by(HistoryRow.seq).all())
        return [{"_seq": r.seq, "type": r.type,
                 "timestamp": r.timestamp,
                 "data": json.loads(r.data or "{}")}
                for r in rows]


def get_design_log(project_dir):
    """设计日志行(带 _seq=行号),供 /design-log 与回滚定位。"""
    pid = _pid(project_dir)
    ensure_tables()
    with SessionLocal() as s:
        rows = (s.query(DesignLogRow).filter_by(project_id=pid)
                .order_by(DesignLogRow.seq).all())
        out = []
        for r in rows:
            try:
                rl = json.loads(r.result_log or "{}")
            except Exception:
                rl = {}
            out.append({"_seq": r.seq, "dltq_seq": r.dltq_seq, "id": r.entry_id,
                        "action": r.action, "instruction": r.instruction,
                        "llm_response": r.llm_response,
                        "output_dir": r.output_dir, "result_log": rl,
                        "q_snapshot": json.loads(r.q_snapshot) if r.q_snapshot else None,
                        "time": r.time, "project_id": r.project_id})
        return out
