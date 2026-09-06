"""Anvil Web UI - FastAPI backend with auth.

Authentication: JWT Bearer token.
Public routes: GET /, POST /api/auth/login, GET /api/auth/me.
All other /api/* routes require authentication.
"""

import os
import sys
import json
import math
import asyncio
import time
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .agent import DesignAgent
from .project.manager import ProjectManager, resolve_project_dir
from .auth import get_current_user
from .db import User, init_db, get_session
from .llm import _get_config, ModelNotConfigured
from .deps import (get_agent, clear_agent, PROJECTS_DIR, user_projects_dir, DATA_DIR,
                   resolve_project_access, PERM_READ, PERM_COMMENT, PERM_EDIT, _PERM_RANK)

app = FastAPI(title="Anvil")

# === 设计任务注册表(切换界面/刷新不中断的支撑) ===
# key = f"{username}:{project_ref}" → 与 deps.get_agent 的 key 一致
# 记录当前/最近一次设计任务的运行状态,前端任何时刻可查询并恢复 UI。
import threading as _threading
_TASKS_LOCK = _threading.Lock()
_TASKS: dict = {}


def _task_key(project_ref, username):
    return (username or "default") + ":" + str(project_ref)


def _task_set(project_ref, username, **fields):
    with _TASKS_LOCK:
        key = _task_key(project_ref, username)
        t = _TASKS.setdefault(key, {"busy": False, "progress": "", "content": "", "files": [],
                                    "step_logs": [], "started_at": None, "finished_at": None,
                                    "error": "", "seq": 0})
        for k, v in fields.items():
            t[k] = v
        _TASKS[key] = t
        return t


def _task_get(project_ref, username):
    with _TASKS_LOCK:
        return _TASKS.get(_task_key(project_ref, username))


# DraftEngine 独立工具调用(HTTP 优先,CLI 降级)
DRAFTENGINE_URL = os.environ.get("DRAFTENGINE_URL", "http://127.0.0.1:8100")
DRAFTENGINE_ROOT = os.environ.get("DRAFTENGINE_ROOT", "/mnt/data/develop/elderly-care-robot/DesignTool/DraftEngine")


def _draftengine_generate(model_path, out_dir, title="", project="", filename=""):
    """调用独立 DraftEngine 生成工程图纸。

    优先 HTTP 服务(8100,快/无进程开销);失败降级 subprocess CLI。
    返回 {svg, pdf, meta} 或 {error}。
    """
    import subprocess
    import urllib.request
    import urllib.parse
    # 1) HTTP
    try:
        body = json.dumps({"model_path": model_path, "out_dir": out_dir,
                           "title": title, "project": project}).encode()
        req = urllib.request.Request(
            DRAFTENGINE_URL + "/api/drawing/from-path", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            r = json.loads(resp.read().decode())
        if "error" not in r:
            return r
    except Exception:
        pass
    # 2) CLI 降级
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = DRAFTENGINE_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "draftengine", model_path,
             "--out-dir", out_dir, "-t", title, "-p", project],
            capture_output=True, text=True, timeout=180, env=env)
        if proc.returncode != 0:
            return {"error": "DraftEngine CLI 失败: " + (proc.stderr or proc.stdout)[:300]}
        # CLI 输出"图纸: <path>",解析产物
        import glob
        base = os.path.splitext(os.path.basename(model_path))[0]
        cand = os.path.join(out_dir, base + "_drawing.svg")
        if os.path.exists(cand):
            return {"svg": cand, "pdf": None, "meta": {}}
        return {"error": "DraftEngine CLI 无产物"}
    except Exception as e:
        return {"error": "DraftEngine 调用失败: " + str(e)}


# CORS — allow frontend dev server origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    project: str
    message: str


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    parent_project: str = ""


class RulesRequest(BaseModel):
    content: str


# === Public routes ===

@app.get("/")
async def index():
    return {"name": "Anvil", "version": "1.0", "status": "ok"}


# === Protected API routes ===

@app.get("/api/structure/search")
async def search_structure_api(q: str = "", user: User = Depends(get_current_user)):
    """检索已知结构模板。?q=储油罐 返回结构骨架 JSON。"""
    if not q:
        return {"error": "缺少 q 参数"}
    from .structure import search_structure
    return search_structure(q)


@app.get("/api/structure/{template_id}")
async def get_structure_detail_api(template_id: int, user: User = Depends(get_current_user)):
    """获取结构模板详情（完整组件骨架）。"""
    from .structure import get_structure_detail
    return get_structure_detail(template_id)


@app.get("/api/primitives")
async def list_primitives_api(user: User = Depends(get_current_user)):
    """列出所有可用的设计原语（图元库），供前端选择工具使用。

    8103 PrimitiveService 优先(动态原语即时可见),失败降级本地 registry。
    """
    try:
        from .primitives_client import list_primitives
        return list_primitives()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/projects")
async def list_projects(all: bool = False, user: User = Depends(get_current_user)):
    """项目列表全走 DB projects 表(用户决策 2026-09-03,废弃文件系统扫描)。

    admin + all=true:返回所有项目;普通用户:自己的+共享的。
    """
    from anvil.db import SessionLocal, ProjectDB as PDB, Share, User as DBUser
    db = SessionLocal()
    try:
        _rows = db.query(PDB).filter(PDB.del_flag == "0").all()
        # parent_map:项目 id → 父项目 id(bigint,供前端组树)
        parent_map = {r.id: r.parent_id for r in _rows if r.parent_id}

        me = db.query(DBUser).filter_by(username=user.username).first()

        def _row_to_proj(r, permission, owner_name):
            dir_name = (r.path or "").rstrip("/").split("/")[-1] or str(r.id)
            return {
                "project_id": r.id,          # 身份统一 bigint
                "name": r.name,
                "dir_name": dir_name,
                "phase": r.phase or "concept",
                "permission": permission,
                "owner": owner_name,
                "parent": parent_map.get(r.id, None),
            }

        # admin + all:全部项目
        if all and me and me.role == "admin":
            uid2name = {u.id: u.username for u in db.query(DBUser).all()}
            return [_row_to_proj(r,
                                  "edit" if r.user_id == me.id else "read",
                                  uid2name.get(r.user_id, "?"))
                    for r in _rows]

        # 普通用户:自己的项目
        own = [_row_to_proj(r, "edit", user.username)
               for r in _rows if r.user_id == (me.id if me else None)]
        # 共享给我的(shares.project_id 为 bigint)
        shared = []
        if me:
            for sh in db.query(Share).filter_by(target_id=me.id).all():
                sr = next((r for r in _rows if r.id == sh.project_id), None)
                if sr:
                    owner = db.query(DBUser).filter_by(id=sh.owner_id).first()
                    shared.append(_row_to_proj(sr, sh.permission,
                                               owner.username if owner else "?"))
        return own + shared
    finally:
        db.close()


# === 数据共享(用户授权其他用户访问自己的项目) ===

class ShareCreateRequest(BaseModel):
    project_id: str
    target_username: str
    permission: str = "read"  # read / comment / edit


@app.get("/api/shares")
async def list_shares(user: User = Depends(get_current_user)):
    """我授权出去的共享列表。"""
    try:
        from anvil.db import SessionLocal, Share, User as DBUser
        db = SessionLocal()
        try:
            me = db.query(DBUser).filter_by(username=user.username).first()
            if not me:
                return []
            rows = db.query(Share).filter_by(owner_id=me.id, del_flag="0").all()
            out = []
            for sh in rows:
                target = db.query(DBUser).filter_by(id=sh.target_id).first()
                out.append({
                    "id": sh.id,
                    "project_id": sh.project_id,
                    "target_username": target.username if target else str(sh.target_id),
                    "permission": sh.permission,
                })
            return out
        finally:
            db.close()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/shares")
async def create_share(req: ShareCreateRequest, user: User = Depends(get_current_user)):
    """授权其他用户访问自己的项目(仅 owner)。"""
    if req.permission not in (PERM_READ, PERM_COMMENT, PERM_EDIT):
        raise HTTPException(status_code=400, detail="permission must be read/comment/edit")
    d, _p, is_owner = resolve_project_access(req.project_id, user.username)
    if d is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not is_owner:
        raise HTTPException(status_code=403, detail="only owner can share")
    try:
        from anvil.db import SessionLocal, Share, User as DBUser, ProjectDB as PDB
        db = SessionLocal()
        try:
            me = db.query(DBUser).filter_by(username=user.username).first()
            target = db.query(DBUser).filter_by(username=req.target_username.strip()).first()
            if not target:
                raise HTTPException(status_code=404, detail="target user not found")
            # project_id 统一 bigint:数字串→id;旧 hash→path 末段反查
            pref = str(req.project_id).strip("/")
            prow = db.query(PDB).filter_by(id=int(pref)).first() if pref.isdigit() else None
            if prow is None:
                prow = db.query(PDB).filter(PDB.path.like("%/" + pref)).first()
            if prow is None:
                raise HTTPException(status_code=404, detail="project not found")
            pid = prow.id
            row = db.query(Share).filter_by(owner_id=me.id, project_id=pid, target_id=target.id).first()
            if row:
                row.permission = req.permission
                row.del_flag = "0"  # 曾撤销的授权重新生效
            else:
                db.add(Share(owner_id=me.id, project_id=pid, target_id=target.id,
                             permission=req.permission, create_by=me.id))
            db.commit()
            return {"success": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/shares/{share_id}")
async def delete_share(share_id: int, user: User = Depends(get_current_user)):
    """撤销共享。"""
    try:
        from anvil.db import SessionLocal, Share, User as DBUser
        db = SessionLocal()
        try:
            me = db.query(DBUser).filter_by(username=user.username).first()
            row = db.query(Share).filter_by(id=share_id, owner_id=me.id if me else -1,
                                            del_flag="0").first()
            if not row:
                raise HTTPException(status_code=404, detail="share not found")
            row.del_flag = "2"  # ruoyi 逻辑删除
            db.commit()
            return {"success": True, "deleted": row.project_id}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/create")
async def create_project(req: CreateProjectRequest, user: User = Depends(get_current_user)):
    """建项目:先 DB insert 拿 bigint id,再用 id 建工作区目录 projects/<user>/<id>/。

    项目信息只在 DB;工作区目录(cad/docs)为设计产物落盘处,不再写 project.json/.anvil.json。
    """
    from .db import SessionLocal, ProjectDB as PDB, User as DBUser
    db = SessionLocal()
    try:
        me = db.query(DBUser).filter_by(username=user.username).first()
        row = PDB(name=req.name, display_name=req.description or "",
                  path="",  # 占位,拿到 id 后回填
                  user_id=me.id if me else None,
                  tenant_id=getattr(user, "tenant_id", None) or "000000",
                  phase="concept",
                  create_by=user.id, update_by=user.id)
        db.add(row)
        db.flush()  # 取自增 bigint id
        project_dir = os.path.join(user_projects_dir(user.username), str(row.id))
        ProjectManager.init_workspace(project_dir)
        row.path = project_dir
        if req.parent_project:
            pref = str(req.parent_project).strip("/")
            pa = db.query(PDB).filter_by(id=int(pref)).first() if pref.isdigit() else None
            if pa is None:
                pa = db.query(PDB).filter(PDB.path.like("%/" + pref)).first()
            if pa is not None:
                row.parent_id = pa.id
        db.commit()
        project_id = row.id
    finally:
        db.close()
    return {"success": True, "project_id": project_id, "name": req.name}


@app.delete("/api/project/{project_ref}")
async def delete_project(project_ref: str, user: User = Depends(get_current_user)):
    project_dir, perm, _own = resolve_project_access(project_ref, user.username)
    if project_dir is None:
        return {"error": "not found"}
    if not _own:
        return {"error": "permission denied: only owner can delete"}
    # 软删 DB(ruoyi 约定 del_flag=2;项目信息以 DB 为准)
    from .db import SessionLocal, ProjectDB as PDB
    db = SessionLocal()
    try:
        ref = str(project_ref).strip("/")
        row = db.query(PDB).filter_by(id=int(ref)).first() if ref.isdigit() else None
        if row is None:
            row = db.query(PDB).filter(PDB.path.like("%/" + ref)).first()
        if row is not None:
            row.del_flag = "2"
            db.commit()
    finally:
        db.close()
    # 清理工作区产物目录
    import shutil
    shutil.rmtree(project_dir, ignore_errors=True)
    clear_agent(project_ref, user.username)
    return {"success": True, "deleted": project_ref}


def _resolve(project_ref: str, username: str = "default", min_perm: str = PERM_READ):
    """Resolve project_ref to project directory with access control.

    自己项目 → edit;共享项目按 shares 权限(read/comment/edit)。
    min_perm 不足 raise 403;找不到 raise 404。
    """
    d, perm, is_owner = resolve_project_access(project_ref, username)
    if d is None:
        raise HTTPException(status_code=404, detail="project not found")
    if _PERM_RANK.get(perm, 0) < _PERM_RANK.get(min_perm, 1):
        raise HTTPException(status_code=403, detail="permission denied (need " + min_perm + ")")
    return d


# === Project detail routes ===

@app.get("/api/project/{project_ref}/docs")
async def list_docs(project_ref: str, user: User = Depends(get_current_user)):
    docs_dir = os.path.join(_resolve(project_ref, user.username), "docs")
    result = {}
    if os.path.exists(docs_dir):
        for section in ["notes", "decisions", "calculations", "changelog"]:
            section_dir = os.path.join(docs_dir, section)
            if os.path.exists(section_dir):
                files = sorted(f for f in os.listdir(section_dir) if f.endswith(".md"))
                result[section] = files
    return result


@app.get("/api/project/{project_ref}/doc/{section}/{filename}")
async def read_doc(project_ref: str, section: str, filename: str, user: User = Depends(get_current_user)):
    path = os.path.join(_resolve(project_ref, user.username), "docs", section, filename)
    if os.path.exists(path):
        return {"content": Path(path).read_text(encoding="utf-8")}
    return {"error": "not found"}


def _load_history_rows(project_dir):
    """读全量历史行(DB 优先,惰性迁移,文件兜底)。"""
    from . import history_db
    return history_db.get_history_rows(project_dir)


def _fold_to_messages(rows):
    """流水账 → 消息气泡列表:tool 行折叠进其后最近 assistant 消息。

    返回 [{type,data,timestamp,seq_range,tools_used}];tools_used=
    [{tool,n}] 该消息前的 tool 流水摘要(名称+次数)。
    """
    msgs = []
    pending_tools = {}  # tool名 → 次数
    seg_start = None
    for e in rows:
        t = e.get("type")
        if seg_start is None:
            seg_start = e.get("_seq")
        if t == "tool":
            name = (e.get("data") or {}).get("tool") or "?"
            pending_tools[name] = pending_tools.get(name, 0) + 1
            continue
        if t in ("user", "assistant"):
            m = {"type": t, "data": e.get("data") or {},
                 "timestamp": e.get("timestamp", ""),
                 "seq_range": [seg_start, e.get("_seq")]}
            if t == "assistant" and pending_tools:
                m["tools_used"] = [{"tool": k, "n": v}
                                   for k, v in sorted(pending_tools.items())]
            pending_tools = {}
            seg_start = None
            msgs.append(m)
    return msgs


@app.get("/api/project/{project_ref}/history")
async def project_history(project_ref: str, page: int = 1, size: int = 200,
                          limit: int = 0, user: User = Depends(get_current_user)):
    """消息级分页历史:tool 流水折叠,旧 limit 参数兼容(优先 page/size)。

    返回 {messages,total_messages,total_pages,page,size};每条 assistant
    消息带 tools_used 摘要与 seq_range(供 /history/detail 下钻全量流水)。
    """
    project_dir = _resolve(project_ref, user.username)
    rows = _load_history_rows(project_dir)
    msgs = _fold_to_messages(rows)
    if limit:  # 老调用兼容:limit=行数 → 等价取末尾消息,原样返回行(不折叠)
        return rows[-limit:]
    total = len(msgs)
    total_pages = max(1, math.ceil(total / size)) if size > 0 else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * size
    return {"messages": msgs[start:start + size], "total_messages": total,
            "total_pages": total_pages, "page": page, "size": size}


@app.get("/api/project/{project_ref}/history/detail")
async def project_history_detail(project_ref: str, from_seq: int, to_seq: int,
                                 user: User = Depends(get_current_user)):
    """下钻:某条消息 seq_range 内的原始流水行(全量 tool 明细可达)。"""
    project_dir = _resolve(project_ref, user.username)
    from . import history_db
    return {"rows": history_db.get_history_range(project_dir, from_seq, to_seq)}


class RollbackRequest(BaseModel):
    seq: int  # 设计日志行号(1-based):恢复到该步【开始前】的模型状态


@app.get("/api/project/{project_ref}/design-log")
async def design_log(project_ref: str, user: User = Depends(get_current_user)):
    """当前项目的设计日志(带序号,序号=文件行号,项目内从 1 开始)。

    每个项目独立管理自己的日志序号:切换项目后序号从该项目第 1 行重新计数。
    """
    project_dir = _resolve(project_ref, user.username)
    from . import history_db
    rows = history_db.get_design_log(project_dir)
    entries = [{
        "seq": r["_seq"],
        "dltq_seq": r.get("dltq_seq"),
        "id": r.get("id", ""),
        "time": r.get("time", ""),
        "action": r.get("action", ""),
        "instruction": r.get("instruction", ""),
        "llm_response": r.get("llm_response", "")[:200],
        "output_dir": r.get("output_dir", ""),
    } for r in rows]
    return entries


@app.post("/api/project/{project_ref}/design-log/rollback")
async def design_log_rollback(project_ref: str, req: RollbackRequest, user: User = Depends(get_current_user)):
    """从设计日志第 seq 步重新设计。

    设计=会话:设计日志每行一步(序号=行号)。指定 seq 后:
    1. 找到第 seq 步之前最近一次成功 model_build 的产物目录
       (每次 build 的 manifest.json 记录了当时的完整模型状态快照);
    2. 用该快照恢复 .model_state.json —— 模型回到"该步开始前"的状态;
    3. clear_agent —— 下一轮对话从恢复点继续(增量修改),而不是重新设计。

    若 seq 之前没有 build(还在需求/概念阶段),则清空模型回到起点。
    """
    project_dir = _resolve(project_ref, user.username, PERM_EDIT)
    from . import history_db
    entries = history_db.get_design_log(project_dir)
    if not entries:
        raise HTTPException(status_code=404, detail="design log not found")
    if req.seq < 1 or req.seq > len(entries):
        raise HTTPException(status_code=400, detail="seq out of range (1..%d)" % len(entries))

    # 找第 seq 步之前最近一次成功 model_build
    # 注意:遇到 model_clear 则模型已清空,不能越过它找更早的 build。
    target_step = None
    for e in entries[:req.seq]:
        if e.get("action") == "model_clear" or (e.get("action") == "tool_call" and "model_clear" in e.get("instruction", "")):
            target_step = None  # 清空之后:模型为空,忽略更早的 build
            continue
        if e.get("action") == "model_build" and e.get("result_log", {}).get("status") == "ok":
            target_step = e.get("output_dir") or ""
    restored_parts = 0
    if target_step:
        # output_dir 形如 cad/{step_id},manifest 记录当时的模型快照
        manifest_path = os.path.join(project_dir, target_step, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            state = {
                "parts": manifest.get("parts", []),
                "joints": manifest.get("joints", []),
                "created_at": None,
                "updated_at": None,
                "schema_version": "1.0",
                "build_counter": 0,
            }
            # build_counter 按 cad/ 已有目录数重算,保持版本连续
            import re
            cad_dir = os.path.join(project_dir, "cad")
            if os.path.isdir(cad_dir):
                state["build_counter"] = len([d for d in os.listdir(cad_dir) if os.path.isdir(os.path.join(cad_dir, d))])
            with open(os.path.join(project_dir, ".model_state.json"), "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            restored_parts = len(state["parts"])
    else:
        # 没有之前的 build → 清空模型
        from anvil.model_state import ModelState
        ModelState(project_dir).clear()
        restored_parts = 0

    # 清 agent 缓存:下一轮会话从恢复点开始(增量修改)
    clear_agent(project_ref, user.username)

    return {
        "ok": True,
        "seq": req.seq,
        "total": len(entries),
        "restored_from": target_step or "(起点/空)",
        "restored_parts": restored_parts,
        "message": "模型已恢复到设计日志第 %d 步开始前的状态，后续指令将基于此状态增量修改。" % req.seq,
    }


# === 机械设计术语表(用户可自助增改) ===

class TermRequest(BaseModel):
    term: str
    definition: str = ""
    geometry: str = ""
    modeling: str = ""


@app.get("/api/terms")
async def list_terms(user: User = Depends(get_current_user)):
    """查询全部机械设计术语(登录即可读)。"""
    from .prompts.mech_terms import get_all_terms
    return get_all_terms()


@app.get("/api/audit/state-writes")
async def state_write_audit(user: User = Depends(get_current_user)):
    """模型状态写入审计(admin):检测是否有非 LLM 工具链(外部直接改)的写入。

    两层检测:
    1. state_writes.jsonl 里的 EXTERNAL(未声明来源)记录;
    2. 每个项目 .model_state.json 的 mtime 若晚于审计里该项目的最后记录
       → 说明被外部直接改过(绕过 ModelState,没走审计)。
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    data_dir = os.environ.get("ANVIL_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    audit_path = os.path.join(data_dir, "state_writes.jsonl")
    records = []
    if os.path.exists(audit_path):
        for line in open(audit_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    external = [r for r in records if "EXTERNAL" in str(r.get("source", ""))]
    # 第二层:对比 mtime——状态文件比审计最后记录还新 = 绕过审计的外部修改
    unmetered = []
    proj_root = os.path.join(data_dir, "projects")
    if os.path.isdir(proj_root):
        last_by_proj = {}
        for r in records:
            last_by_proj[r.get("project", "")] = r.get("time", "")
        for uname in sorted(os.listdir(proj_root)):
            udir = os.path.join(proj_root, uname)
            if not os.path.isdir(udir):
                continue
            for dname in sorted(os.listdir(udir)):
                state_path = os.path.join(udir, dname, ".model_state.json")
                if not os.path.exists(state_path):
                    continue
                mtime = datetime.fromtimestamp(os.path.getmtime(state_path)).isoformat()
                last_audit = last_by_proj.get(dname, "")
                if mtime > last_audit:
                    unmetered.append({
                        "project": dname,
                        "state_mtime": mtime,
                        "last_audit": last_audit or "(无审计记录)",
                        "suspicious": True,
                    })
    return {"records": records[-200:], "external": external, "unmetered": unmetered}


@app.get("/api/guardian")
async def guardian_records(user: User = Depends(get_current_user)):
    """监护者记录(admin/engineer):Anvil 做错/碰到的问题 + 修正建议。

    原则:监护者看着 Anvil 做事,记录对错,针对性修正(不是替它完成,
    而是修正它让它能完成)。此接口供开发侧查看并落实修正。
    """
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="需要工程师/管理员权限")
    from .guardian import list_guardian
    data_dir = os.environ.get("ANVIL_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    return list_guardian(data_dir)


@app.post("/api/guardian/{index}/status")
async def update_guardian_status(index: int, req: dict, user: User = Depends(get_current_user)):
    """标记监护记录状态(open/resolved)——开发侧修正后标记。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    status = req.get("status", "")
    if status not in ("open", "resolved"):
        raise HTTPException(status_code=400, detail="status 必须为 open/resolved")
    from .guardian import list_guardian
    from anvil.comm import COMM_DIR
    data_dir = os.environ.get("ANVIL_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    guard_path = os.path.join(data_dir, "guardian.jsonl")
    if not os.path.exists(guard_path):
        raise HTTPException(status_code=404, detail="无监护记录")
    lines = open(guard_path, encoding="utf-8").readlines()
    # list_guardian 返回倒序,index 对应倒序位置
    recs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            continue
    if index < 0 or index >= len(recs):
        raise HTTPException(status_code=400, detail="index 越界")
    # 倒序第 index 条 = 正序第 (len-1-index) 条
    pos = len(recs) - 1 - index
    recs[pos]["status"] = status
    with open(guard_path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"ok": True, "status": status}


@app.get("/api/design-loop")
async def design_loop_queue(user: User = Depends(get_current_user)):
    """设计循环状态(admin/engineer):各设计任务的缺口→方案→重做→审阅→调整→重做。

    用户定的流程:Anvil 解决不了→抛缺口→后端给原语方案→Anvil重做→审阅→
    发现问题调原语→重做(反复直至正确)。此接口查看各任务状态。
    """
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="需要工程师/管理员权限")
    from anvil.comm import list_jobs
    jobs = list_jobs(limit=500)
    statuses = {}
    for j in jobs:
        st = j.get("status", "?")
        statuses[st] = statuses.get(st, 0) + 1
    return {
        "total": len(jobs),
        "count_by_status": statuses,
        "recent": jobs[:20],
    }


@app.get("/api/capability-gaps")
async def list_capability_gaps(user: User = Depends(get_current_user)):
    """能力缺口清单(admin/engineer):Anvil 响应不了、显式提交的需求。

    原则:Anvil 遇到表达不了的需求必须暴露为缺口(不许硬凑),
    开发侧查此清单 → 实现能力 → 标记 status=implemented → Anvil 即可用。
    """
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="需要工程师/管理员权限")
    from anvil.comm import COMM_DIR
    gap_path = os.path.join(COMM_DIR, "capability_gaps.jsonl")
    if not os.path.exists(gap_path):
        return []
    gaps = []
    for line in open(gap_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            gaps.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(gaps))  # 新的在前


@app.post("/api/capability-gaps/{gap_id}/status")
async def update_capability_gap(gap_id: str, req: dict, user: User = Depends(get_current_user)):
    """标记能力缺口状态(implemented/rejected)——开发侧实现后调用。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    status = req.get("status", "")
    if status not in ("implemented", "rejected"):
        raise HTTPException(status_code=400, detail="status 必须为 implemented/rejected")
    from anvil.comm import COMM_DIR
    gap_path = os.path.join(COMM_DIR, "capability_gaps.jsonl")
    if not os.path.exists(gap_path):
        raise HTTPException(status_code=404, detail="无缺口记录")
    lines = open(gap_path, encoding="utf-8").readlines()
    found = False
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("id") == gap_id:
            rec["status"] = status
            lines[i] = json.dumps(rec, ensure_ascii=False) + "\n"
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="缺口不存在: " + gap_id)
    with open(gap_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return {"ok": True, "id": gap_id, "status": status}


@app.post("/api/terms")
async def create_term(req: TermRequest, user: User = Depends(get_current_user)):
    """新增术语(engineer/admin)。"""
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="需要工程师/管理员权限")
    from anvil.db import SessionLocal, MechTerm
    term = req.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="术语名不能为空")
    db = SessionLocal()
    try:
        if db.query(MechTerm).filter_by(term=term).first():
            raise HTTPException(status_code=400, detail="术语已存在")
        db.add(MechTerm(term=term, definition=req.definition, geometry=req.geometry, modeling=req.modeling))
        db.commit()
        return {"ok": True, "term": term}
    finally:
        db.close()


@app.put("/api/terms/{term_id}")
async def update_term(term_id: int, req: TermRequest, user: User = Depends(get_current_user)):
    """更新术语(engineer/admin)。"""
    if user.role not in ("admin", "engineer"):
        raise HTTPException(status_code=403, detail="需要工程师/管理员权限")
    from anvil.db import SessionLocal, MechTerm
    db = SessionLocal()
    try:
        row = db.query(MechTerm).filter_by(id=term_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="术语不存在")
        row.term = req.term.strip()
        row.definition = req.definition
        row.geometry = req.geometry
        row.modeling = req.modeling
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.delete("/api/terms/{term_id}")
async def delete_term(term_id: int, user: User = Depends(get_current_user)):
    """删除术语(admin)。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    from anvil.db import SessionLocal, MechTerm
    db = SessionLocal()
    try:
        row = db.query(MechTerm).filter_by(id=term_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="术语不存在")
        db.delete(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/project/{project_ref}/status")
async def project_status(project_ref: str, user: User = Depends(get_current_user)):
    agent = get_agent(project_ref, user.username)
    if not agent:
        return {"error": "project not found"}
    return {"status": agent.get_status()}


@app.get("/api/project/{project_ref}/rules")
async def get_rules(project_ref: str, user: User = Depends(get_current_user)):
    path = os.path.join(_resolve(project_ref, user.username), ".rules.md")
    if os.path.exists(path):
        return {"content": Path(path).read_text(encoding="utf-8")}
    return {"content": ""}


@app.put("/api/project/{project_ref}/rules")
async def update_rules(project_ref: str, req: RulesRequest, user: User = Depends(get_current_user)):
    path = os.path.join(_resolve(project_ref, user.username, PERM_COMMENT), ".rules.md")
    Path(path).write_text(req.content, encoding="utf-8")
    clear_agent(project_ref)
    return {"success": True}


# === Gantt chart data (per project) ===

class GanttRequest(BaseModel):
    data: str  # JSON string of gantt tasks


@app.get("/api/project/{project_ref}/gantt")
async def get_gantt(project_ref: str, user: User = Depends(get_current_user)):
    path = os.path.join(_resolve(project_ref, user.username), ".gantt.json")
    if os.path.exists(path):
        return {"content": Path(path).read_text(encoding="utf-8")}
    return {"content": ""}


@app.put("/api/project/{project_ref}/gantt")
async def update_gantt(project_ref: str, req: GanttRequest, user: User = Depends(get_current_user)):
    path = os.path.join(_resolve(project_ref, user.username, PERM_COMMENT), ".gantt.json")
    Path(path).write_text(req.data, encoding="utf-8")
    return {"success": True}


@app.get("/api/gantt/list")
async def list_gantt_files(user: User = Depends(get_current_user)):
    """列出已保存甘特图的项目(项目信息走 DB),供前端「从服务器打开」选择。"""
    from anvil.db import SessionLocal, ProjectDB as PDB, User as DBUser
    items = []
    db = SessionLocal()
    try:
        me = db.query(DBUser).filter_by(username=user.username).first()
        rows = db.query(PDB).filter(PDB.del_flag == "0").all()
        if not (me and me.role == "admin"):
            rows = [r for r in rows if r.user_id == (me.id if me else None)]
        for r in rows:
            if not r.path:
                continue
            gantt_path = os.path.join(r.path, ".gantt.json")
            if not os.path.isfile(gantt_path):
                continue
            task_count = 0
            try:
                data = json.loads(Path(gantt_path).read_text(encoding="utf-8"))
                if isinstance(data, list):
                    task_count = len(data)
            except Exception:
                pass
            items.append({
                "project_id": r.id,
                "name": r.name,
                "dir_name": r.path.rstrip("/").split("/")[-1],
                "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(gantt_path))),
                "task_count": task_count,
            })
    finally:
        db.close()
    items.sort(key=lambda x: x["updated"], reverse=True)
    return {"files": items}


# === Material (standard parts) query proxy — worker02 mn-material service ===

MATERIAL_BASE = os.environ.get("MATERIAL_BASE", "http://127.0.0.1:8080/material")


@app.get("/api/material/{collection}/list")
def material_list(collection: str,
                        name: str = "", categoryId: str = "", brand: str = "",
                        keyword: str = "", pageNum: int = 1, pageSize: int = 20):
    """Proxy to mn-material service. ssh 8095(production)直接调 material_client;本地 8093 转发."""
    import urllib.request, urllib.parse
    allowed = {"partCategory", "standardPart", "nonstandardPart", "industryPart", "enterprisePart", "supplierInfo", "searchCache"}
    if collection not in allowed:
        raise HTTPException(status_code=404, detail="unknown collection")
    if os.environ.get("ANVIL_ENV") == "production":
        from anvil.material_client import (
            list_categories, search_standard_parts, search_nonstandard_parts,
            search_industry_parts, search_enterprise_parts,
            list_suppliers, search_cache,
        )
        try:
            if collection == "partCategory":
                return list_categories()
            if collection == "standardPart":
                return search_standard_parts(name=name or None, category_id=categoryId or None,
                                             brand=brand or None, page=pageNum, page_size=pageSize)
            if collection == "nonstandardPart":
                return search_nonstandard_parts(name=name or None, category_id=categoryId or None,
                                                page=pageNum, page_size=pageSize)
            if collection == "industryPart":
                return search_industry_parts(name=name or None, category_id=categoryId or None,
                                             page=pageNum, page_size=pageSize)
            if collection == "enterprisePart":
                return search_enterprise_parts(name=name or None, category_id=categoryId or None,
                                               page=pageNum, page_size=pageSize)
            if collection == "supplierInfo":
                return list_suppliers(name=name or None)
            if collection == "searchCache":
                return search_cache(keyword=keyword or None)
            return {"status": "error", "message": "unknown collection"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    base = os.environ.get("MATERIAL_PROXY_BASE", "http://127.0.0.1:8095")
    params = {"pageNum": pageNum, "pageSize": pageSize}
    if name: params["name"] = name
    if categoryId: params["categoryId"] = categoryId
    if brand: params["brand"] = brand
    if keyword: params["keyword"] = keyword
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{base}/api/material/{collection}/list?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "message": str(e)}


class MaterialMatchRequest(BaseModel):
    name: str = ""
    category_id: int | None = None
    constraints: dict = {}
    limit: int = 10
    strategy: bool = False      # True=按企业自有>行业>标准>非标 优选
    prefer: str = ""            # 指定只看某层: enterprise/industry/standard/nonstandard


@app.post("/api/material/match")
def material_match(req: MaterialMatchRequest):
    """标准件选用匹配:按设计约束(规格/载荷/尺寸)从标准件库选出匹配零件。
    strategy=True 时按优先级选型:企业自有 → 行业 → 标准 → 非标。
    ssh 8095(生产):直接调用 material_client;本地 8093(开发):转发到 ssh 8095。
    """
    import urllib.request
    base = os.environ.get("MATERIAL_PROXY_BASE", "http://127.0.0.1:8095")
    payload = {
        "name": req.name, "category_id": req.category_id,
        "constraints": req.constraints, "limit": req.limit,
        "strategy": req.strategy, "prefer": req.prefer,
    }
    if os.environ.get("ANVIL_ENV") == "production":
        # ssh 8095 直接调用本地 material_client(复用 SampleClient)
        from anvil.material_client import match_standard_parts, select_with_strategy
        if req.strategy or req.prefer:
            return select_with_strategy(name=req.name or None,
                                        constraints=req.constraints,
                                        limit=req.limit,
                                        prefer=req.prefer or None)
        return match_standard_parts(name=req.name or None,
                                    category_id=req.category_id,
                                    constraints=req.constraints,
                                    limit=req.limit)
    # 本地开发:转发到 ssh 8095 的 match
    url = f"{base}/api/material/match"
    try:
        data = json.dumps(payload).encode()
        fwd = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(fwd, timeout=40) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "message": str(e)}


# === Reviews ===

@app.get("/api/project/{project_ref}/reviews")
async def list_reviews(project_ref: str, user: User = Depends(get_current_user)):
    from anvil.review_manager import ReviewManager
    rm = ReviewManager(_resolve(project_ref, user.username))
    return {"reviews": rm.list()}


@app.post("/api/project/{project_ref}/reviews")
async def submit_review_api(project_ref: str, req: dict, user: User = Depends(get_current_user)):
    from anvil.review_manager import ReviewManager
    rm = ReviewManager(_resolve(project_ref, user.username))
    label = req.get("label", "")
    result = rm.submit(label)
    return result


@app.get("/api/project/{project_ref}/reviews/{review_id}")
async def get_review(project_ref: str, review_id: str, user: User = Depends(get_current_user)):
    from anvil.review_manager import ReviewManager
    rm = ReviewManager(_resolve(project_ref, user.username))
    result = rm.get(review_id)
    if not result:
        return {"error": "not found"}
    return result


@app.post("/api/project/{project_ref}/reviews/{review_id}/items")
async def add_review_item(project_ref: str, review_id: str, req: dict, user: User = Depends(get_current_user)):
    from anvil.review_manager import ReviewManager
    rm = ReviewManager(_resolve(project_ref, user.username))
    result = rm.add_item(
        review_id, req.get("severity", "一般"),
        req.get("category", "其他"), req.get("component", ""),
        req.get("title", ""), req.get("description", ""),
        req.get("suggestion", ""), req.get("created_by", "reviewer"))
    return result


# === CAD files ===

def _cad_fullpath(project_dir, path):
    """cad/ 下相对路径 → 本地绝对路径;本地缺失时从 MinIO 回源(本地=缓存,MinIO=持久库)。

    含越权防护(防 path 遍历)。找不到抛 404。
    """
    full = os.path.realpath(os.path.join(project_dir, "cad", path))
    cad_real = os.path.realpath(os.path.join(project_dir, "cad"))
    if not full.startswith(cad_real):
        raise HTTPException(status_code=403, detail="access denied")
    if os.path.exists(full):
        return full
    try:
        pid = ProjectManager(project_dir).pid
        from . import minio_store
        if minio_store.download_to(pid, "cad/" + path, full):
            return full
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="file not found")


@app.get("/api/project/{project_ref}/cad/")
async def list_cad(project_ref: str, user: User = Depends(get_current_user)):
    project_dir = _resolve(project_ref, user.username)
    mgr = ProjectManager(project_dir)
    files = list(mgr.list_cad_files_full())
    # 合并 MinIO 持久产物(本地缓存可能已清);MinIO rel 形如 cad/step_1.stl → 去 cad/ 前缀
    try:
        from . import minio_store
        pid = mgr.pid
        have = set(files)
        for rel in minio_store.list_relfiles(pid):
            if not rel.startswith("cad/"):
                continue
            sub = rel[len("cad/"):]
            if sub.startswith("_archive/"):
                continue  # 归档快照不进当前产物列表
            if sub not in have:
                files.append(sub)
    except Exception:
        pass
    return files


def log_download(username: str, project_ref: str, file_path: str, action: str, size: int = 0):
    """统一文件下载追溯日志(JSON Lines):data/downloads.jsonl。

    记录谁在什么时间对哪个项目的哪个文件做了什么(download/view)。
    """
    import time as _time
    try:
        log_path = os.path.join(DATA_DIR, "downloads.jsonl")
        entry = {
            "time": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "project": project_ref,
            "file": file_path,
            "action": action,  # download / view
            "size": size,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败不阻断下载


@app.get("/api/project/{project_ref}/cad/{path:path}/view")
async def view_cad(project_ref: str, path: str, user: User = Depends(get_current_user)):
    project_dir = _resolve(project_ref, user.username)
    full = _cad_fullpath(project_dir, path)
    log_download(user.username, project_ref, "cad/" + path, "view", os.path.getsize(full))
    content = Path(full).read_text(encoding="utf-8", errors="replace")
    return PlainTextResponse(content)


@app.get("/api/project/{project_ref}/cad/{path:path}/preview3d")
async def preview_cad_3d(project_ref: str, path: str, user: User = Depends(get_current_user)):
    """内嵌查看 STEP:后端用 OCP(OpenCascade)把 STEP 转 VRML,前端 three.js 直接渲染,无需下载。

    支持 .step/.stp;.stl 直接返回原文件(前端已有 STL 渲染)。
    """
    project_dir = _resolve(project_ref, user.username)
    full = _cad_fullpath(project_dir, path)
    log_download(user.username, project_ref, "cad/" + path, "preview3d", os.path.getsize(full))
    ext = os.path.splitext(full)[1].lower()
    if ext in (".stl",):
        return FileResponse(full, media_type="application/octet-stream")
    if ext not in (".step", ".stp"):
        raise HTTPException(status_code=415, detail="unsupported format for 3d preview")
    # STEP → VRML(OCP 本地转换,保留 CAD 语义)
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.VrmlAPI import VrmlAPI_Writer
        r = STEPControl_Reader()
        if r.ReadFile(str(full)) != IFSelect_RetDone:
            raise HTTPException(status_code=500, detail="STEP parse failed")
        r.TransferRoots()
        shape = r.OneShape()
        # 关键两步(缺一只能导出线框 IndexedLineSet,无曲面):
        # ① BRepMesh 三角化(VrmlAPI 写面需要 mesh);deflection 0.5mm 平滑度/体积折中
        # ② SetRepresentation(Shaded) 只出面(Both 混线框会闪)
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.VrmlAPI import VrmlAPI_RepresentationOfShape
        BRepMesh_IncrementalMesh(shape, 0.5, False, 0.5, True)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".wrl", delete=False)
        tmp.close()
        w = VrmlAPI_Writer()
        w.SetRepresentation(VrmlAPI_RepresentationOfShape.VrmlAPI_ShadedRepresentation)
        w.Write(shape, tmp.name)
        vrml = Path(tmp.name).read_bytes()
        os.unlink(tmp.name)
        return Response(content=vrml, media_type="model/vrml")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="STEP to VRML failed: " + str(e))


@app.get("/api/project/{project_ref}/cad/{path:path}/drawing")
async def project_drawing(project_ref: str, path: str, fmt: str = "svg", user: User = Depends(get_current_user)):
    """STEP → 工程图纸(三视图 SVG/PDF)。

    fmt: svg(默认,前端内嵌显示) / pdf(下载/打印)
    产物缓存到 cad/{step_dir}/drawing.svg|pdf(与 STEP 同目录,可追溯)。

    注意:必须在 download_cad 之前注册,否则 {path:path} 会贪婪吞掉 /drawing 后缀。
    """
    project_dir = _resolve(project_ref, user.username)
    if not path.endswith((".step", ".stp")):
        raise HTTPException(status_code=404, detail="STEP file not found")
    step_full = _cad_fullpath(project_dir, path)  # 本地缺失则从 MinIO 回源
    # 产物目录 = STEP 所在目录;项目名走 DB(不再读 .anvil.json)
    out_dir = os.path.dirname(step_full)
    proj_name = project_ref
    try:
        proj_name = ProjectManager(project_dir).get_config().get("name", project_ref)
    except Exception:
        pass
    # 调用独立 DraftEngine 工具(HTTP 优先,失败降级 CLI)
    result = _draftengine_generate(step_full, out_dir, title=proj_name, project=proj_name,
                                   filename=os.path.basename(path))
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    if fmt == "pdf":
        if not result.get("pdf"):
            raise HTTPException(status_code=500, detail="PDF 生成失败")
        log_download(user.username, project_ref, "cad/" + path + "/drawing.pdf", "download", os.path.getsize(result["pdf"]))
        return FileResponse(result["pdf"], filename=os.path.basename(path).replace(".step", ".pdf").replace(".stp", ".pdf"),
                            media_type="application/pdf")
    log_download(user.username, project_ref, "cad/" + path + "/drawing.svg", "view", os.path.getsize(result["svg"]))
    return FileResponse(result["svg"], filename=os.path.basename(path).replace(".step", "_drawing.svg").replace(".stp", "_drawing.svg"),
                        media_type="image/svg+xml")


@app.get("/api/project/{project_ref}/cad/{path:path}")
async def download_cad(project_ref: str, path: str, user: User = Depends(get_current_user)):
    project_dir = _resolve(project_ref, user.username)
    full = _cad_fullpath(project_dir, path)
    log_download(user.username, project_ref, "cad/" + path, "download", os.path.getsize(full))
    return FileResponse(full, filename=os.path.basename(path), media_type="application/octet-stream")



@app.get("/api/project/{project_ref}/uploads/{filename}")
async def serve_upload(project_ref: str, filename: str, user: User = Depends(get_current_user)):
    path = os.path.join(_resolve(project_ref, user.username), "uploads", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    log_download(user.username, project_ref, "uploads/" + filename, "download", os.path.getsize(path))
    return FileResponse(path, filename=filename)


@app.post("/api/project/{project_ref}/preview-step")
async def preview_step_upload(project_ref: str, file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """导入 STEP 文件 → OCP 转 VRML → 返回(内嵌查看,不落盘)。"""
    _resolve(project_ref, user.username)  # 校验权限(至少可读)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large")
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.VrmlAPI import VrmlAPI_Writer
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".step", delete=False)
        tmp.write(data)
        tmp.close()
        try:
            r = STEPControl_Reader()
            if r.ReadFile(tmp.name) != IFSelect_RetDone:
                raise HTTPException(status_code=400, detail="STEP parse failed")
            r.TransferRoots()
            shape = r.OneShape()
            vtmp = tempfile.NamedTemporaryFile(suffix=".wrl", delete=False)
            vtmp.close()
            w = VrmlAPI_Writer()
            w.Write(shape, vtmp.name)
            vrml = Path(vtmp.name).read_bytes()
            os.unlink(vtmp.name)
        finally:
            os.unlink(tmp.name)
        return Response(content=vrml, media_type="model/vrml")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="STEP to VRML failed: " + str(e))


# === Sketch & Scene (routers) ===
from .routers.sketch_router import router as sketch_router
from .routers.scene_router import router as scene_router
from .demo_api import router as demo_router
from .demo_gen import router as demo_gen_router
from .routers.encoder_router import router as encoder_router

def ensure_project_parent_col():
    """projects 表结构迁移(MySQL/SQLite 兼容,幂等):
    parent_id 分级 + ruoyi-cloud-plus 多租户字段(tenant_id/审计/del_flag)。"""
    from .db import engine
    from sqlalchemy import text
    cols = [
        "ALTER TABLE projects ADD COLUMN parent_id INT NULL",
        "ALTER TABLE projects ADD COLUMN tenant_id VARCHAR(20) DEFAULT 000000",
        "ALTER TABLE projects ADD COLUMN create_dept BIGINT NULL",
        "ALTER TABLE projects ADD COLUMN create_by VARCHAR(64) DEFAULT ",
        "ALTER TABLE projects ADD COLUMN create_time DATETIME NULL",
        "ALTER TABLE projects ADD COLUMN update_by VARCHAR(64) DEFAULT ",
        "ALTER TABLE projects ADD COLUMN update_time DATETIME NULL",
        "ALTER TABLE projects ADD COLUMN del_flag CHAR(1) DEFAULT 0",
    ]
    with engine.connect() as c:
        for ddl in cols:
            try:
                c.execute(text(ddl))
                c.commit()
            except Exception:
                pass
ensure_project_parent_col()

app.include_router(sketch_router)
app.include_router(scene_router)
app.include_router(demo_router)
app.include_router(demo_gen_router)
app.include_router(encoder_router)


# === Chat ===
@app.post("/api/chat")
async def chat(req: ChatRequest, user: User = Depends(get_current_user)):
    d, perm, _own = resolve_project_access(req.project, user.username)
    if d is None:
        return {"error": "project not found"}
    if _PERM_RANK.get(perm, 0) < _PERM_RANK.get(PERM_EDIT, 3):
        return {"error": "permission denied: need edit"}
    agent = get_agent(req.project, user.username)
    if not agent:
        return {"error": "project not found"}

    # 模型配置策略:非测试用户必须自配推理模型才能发起 AI 设计
    try:
        _get_config("text", user_id=user.id)
    except ModelNotConfigured:
        _err = json.dumps({"type": "error", "code": "MODEL_NOT_CONFIGURED",
                           "content": "未配置模型:请先在「设置 → 模型配置」中配置推理模型,再使用 AI 设计"})
        def _err_stream():
            yield "data: " + _err + "\n"
        return StreamingResponse(_err_stream(), media_type="text/event-stream")

    _task_set(req.project, user.username, busy=True, progress="启动中...", content="",
              files=[], step_logs=[], error="", started_at=datetime.now().isoformat(),
              finished_at=None)

    async def stream():
        try:
            # ── 译码自动路由(2026-09-06)────────────────────────────
            # 每轮先试译:矩阵非空 → 译码快路径(落账+执行);矩阵空+有备注 →
            # 纯回应;译码失败/超纲(9999)/异常 → 降级原 agent 工具循环。
            enc_events = None
            try:
                from anvil.encoder.encoder import translate as _enc_translate
                from anvil.encoder.ledger import DltQLedger as _DltQLedger
                _led = _DltQLedger(agent.project_dir)
                # 指称索引快照(与 run_round 同构:names 指称锚 + 原指令 + 心象位置——
                # chat 主路径的引用锚定不能弱于 translate 直调路径)
                from anvil.routers.encoder_router import _pos_str as _ps
                _hist = [{"seq": e["seq"], "names": "／".join(e.get("names") or []),
                          "echo": e.get("echo", ""),
                          "source": (e.get("source") or "")[:60],
                          "pos": _ps(e.get("topo"))}
                         for e in _led.all_entries()]
                _task_set(req.project, user.username, progress="译码中...")
                from . import history_db as _hdb
                _enc = _enc_translate(req.message, user_id=getattr(agent, "user_id", None),
                                      history=_hist,
                                      recent=_hdb.get_recent_dialog(agent.project_dir))
                if _enc["ok"] and _enc["dltq"]:
                    _task_set(req.project, user.username, progress="执行中...")
                    from anvil.routers.encoder_router import run_round
                    res = run_round(agent, req.message, enc_result=_enc)
                    if res.get("error"):
                        enc_events = ["data: " + json.dumps({"type": "error", "content": res["error"]})]
                    else:
                        _txt = (res.get("echo", "") + ("\n\n" + (res.get("note") or ""))).strip()
                        evs = []
                        if _txt:
                            evs.append({"type": "token", "content": _txt})
                        for f in res.get("files", []):
                            evs.append({"type": "file", "content": f})
                        if not res.get("exec_ok"):
                            evs.append({"type": "error", "content": res.get("exec_error") or "执行失败"})
                        enc_events = ["data: " + json.dumps(e) for e in evs]
                elif _enc["ok"] and _enc.get("note"):
                    agent.history.append("user", {"content": req.message})
                    agent.history.append("assistant", {"content": _enc["note"]})
                    enc_events = ["data: " + json.dumps({"type": "token", "content": _enc["note"]})]
                elif not _enc["ok"]:
                    # 译码失败降级 agent:技术细节只进服务端日志(设计者界面
                    # 只见 agent 回应,2026-09-06 用户定);留痕写设计日志便于后续优化
                    print("[encode] 译码失败降级 agent(内部详情):",
                          _enc.get("error"), "| raw:", (_enc.get("raw") or "")[:150], flush=True)
                    try:
                        agent.project.append_log({
                            "action": "encode_fail",
                            "instruction": req.message,
                            "llm_response": "(降级对话回应)",
                            "output_dir": "",
                            "result_log": {
                                "status": "encode_fail_fallback_agent",
                                "internal": _enc.get("error"),
                                "raw": (_enc.get("raw") or "")[:500],
                                "trace": _enc.get("_trace") or [],
                            },
                        })
                    except Exception:
                        pass
            except Exception:
                enc_events = None  # 路由异常 → agent 兜底

            if enc_events is not None:
                for e in enc_events:
                    try:
                        j = json.loads(e[6:])
                        et = j.get("type")
                        if et == "token":
                            _task_set(req.project, user.username, content=(_task_get(req.project, user.username) or {}).get("content", "") + (j.get("content") or ""))
                        elif et == "file":
                            _task_set(req.project, user.username, files=(_task_get(req.project, user.username) or {}).get("files", []) + [j.get("content", "")])
                        elif et == "error":
                            _task_set(req.project, user.username, error=j.get("content", ""))
                    except Exception:
                        pass
                    yield e + "\n"
                return
            # ── 降级:原 agent 工具循环 ──────────────────────────────
            import queue as _queue
            q = _queue.Queue()
            def _run_gen():
                try:
                    for event in agent.chat_stream(req.message):
                        q.put(event)
                        # 生产者线程直接更新注册表——即使客户端断开/切走,
                        # 任务状态也持续跟踪到结束(前端恢复时拿到完整结果)。
                        try:
                            j = json.loads(event)
                            et = j.get("type")
                            if et == "token":
                                _task_set(req.project, user.username, content=(_task_get(req.project, user.username) or {}).get("content", "") + (j.get("content") or ""))
                            elif et == "progress":
                                _task_set(req.project, user.username, progress=j.get("content", ""))
                            elif et == "step":
                                _task_set(req.project, user.username, step_logs=(_task_get(req.project, user.username) or {}).get("step_logs", []) + [j.get("content", "")])
                            elif et == "file":
                                _task_set(req.project, user.username, files=(_task_get(req.project, user.username) or {}).get("files", []) + [j.get("content", "")])
                            elif et == "error":
                                _task_set(req.project, user.username, error=j.get("content", ""))
                        except Exception:
                            pass
                except Exception as e:
                    q.put(json.dumps({"type": "error", "content": str(e)}))
                finally:
                    q.put(None)
            asyncio.create_task(asyncio.to_thread(_run_gen))
            while True:
                event = await asyncio.to_thread(lambda: q.get())
                if event is None:
                    break
                yield "data: " + event
        except Exception as e:
            _task_set(req.project, user.username, error=str(e), busy=False, finished_at=datetime.now().isoformat())
            yield "data: " + json.dumps({"type": "error", "content": str(e)}) + "\n"
        finally:
            _task_set(req.project, user.username, busy=False, finished_at=datetime.now().isoformat())

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/project/{project_ref}/task/status")
async def task_status(project_ref: str, user: User = Depends(get_current_user)):
    """查询项目当前设计任务状态(进行中/最近一次结果)。用于切走/刷新后恢复 UI。"""
    d, perm, _own = resolve_project_access(project_ref, user.username)
    if d is None:
        raise HTTPException(status_code=404, detail="project not found")
    t = _task_get(project_ref, user.username)
    if t is None:
        return {"busy": False, "progress": "", "content": "", "files": [], "step_logs": [],
                "started_at": None, "finished_at": None, "error": ""}
    return t


@app.post("/api/chat/with-files")
async def chat_with_files(
    project: str = Form(...),
    message: str = Form(""),
    files: list[UploadFile] = File(None),
    user: User = Depends(get_current_user),
):
    d, perm, _own = resolve_project_access(project, user.username)
    if d is None:
        return {"error": "project not found"}
    if _PERM_RANK.get(perm, 0) < _PERM_RANK.get(PERM_EDIT, 3):
        return {"error": "permission denied: need edit"}
    agent = get_agent(project, user.username)
    if not agent:
        return {"error": "project not found"}

    # 模型配置策略:非测试用户必须自配推理模型才能发起 AI 设计
    try:
        _get_config("text", user_id=user.id)
    except ModelNotConfigured:
        _err = json.dumps({"type": "error", "code": "MODEL_NOT_CONFIGURED",
                           "content": "未配置模型:请先在「设置 → 模型配置」中配置推理模型,再使用 AI 设计"})
        def _err_stream2():
            yield "data: " + _err + "\n"
        return StreamingResponse(_err_stream2(), media_type="text/event-stream")

    full_message = message or ""
    refs = []
    if files:
        project_dir, _ = resolve_project_dir(user_projects_dir(user.username), project)
        if project_dir is None:
            return {"error": "project not found"}
        upload_dir = os.path.join(project_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        for f in files:
            ext = os.path.splitext(f.filename or "file")[1].lower()
            safe_name = f.filename.replace(" ", "_") or "file"
            dest = os.path.join(upload_dir, safe_name)
            content = await f.read()
            with open(dest, "wb") as fout:
                fout.write(content)
            TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".py", ".js", ".html", ".xml", ".yaml", ".yml", ".log"}
            if ext in TEXT_EXTS:
                text = content.decode("utf-8", errors="replace")
                if full_message:
                    full_message += "\n\n---\n\n"
                full_message += text
            else:
                refs.append(f.filename or "file")
        if refs:
            full_message += "\n\n[Attached: " + ", ".join(refs) + "]"
    async def stream():
        try:
            import queue as _queue
            q = _queue.Queue()
            def _run_gen():
                for event in agent.chat_stream(full_message):
                    q.put(event)
                q.put(None)
            asyncio.create_task(asyncio.to_thread(_run_gen))
            while True:
                event = await asyncio.to_thread(lambda: q.get())
                if event is None:
                    break
                yield "data: " + event
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "content": str(e)}) + "\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/interpret")
async def interpret_design(
    scene: str = Form(""),
    llm_config: str = Form(""),
    file: UploadFile = File(None),
    mode: str = Form("structure"),
    followup: str = Form(""),
    history: str = Form("[]"),
    user: User = Depends(get_current_user),
):
    """AI 解读：结构解读（scene JSON）或图像解读（PNG → Vision LLM）。
    
    mode=structure: 用推理 LLM 解读 scene JSON（需要 scene 参数）
    mode=vision:    用 Vision LLM 解读画布截图（需要 file 参数）

    模型配置一律服务端解析(用户自配优先),前端 llm_config 不再作为密钥来源。
    """
    def _stream_error(msg: str, code: str = ""):
        payload = {"type": "error", "content": msg}
        if code:
            payload["code"] = code
        return StreamingResponse(
            iter(["data: " + json.dumps(payload) + "\n"]),
            media_type="text/event-stream",
        )

    # 服务端解析模型配置(策略:非测试用户必须自配)
    try:
        if mode == "vision":
            v_base_url, v_api_key, v_model = _get_config("vision", user_id=user.id)
        else:
            base_url, api_key, model = _get_config("text", user_id=user.id)
    except ModelNotConfigured as e:
        kind_label = "视觉" if e.kind == "vision" else "推理"
        return _stream_error(
            f"未配置{kind_label}模型:请先在「设置 → 模型配置」中配置后再使用 AI 解读",
            code="MODEL_NOT_CONFIGURED")

    if mode == "vision":
        if not v_api_key:
            return _stream_error("视觉模型未配置 API Key,请在「设置 → 模型配置」中补全")

        # 构建消息：如有 followup 则用多轮对话，用户消息附带图片
        if followup:
            messages = []
            try:
                hist = json.loads(history) if history else []
                for m in hist:
                    messages.append({"role": m["role"], "content": m["content"]})
            except Exception:
                pass
            if file:
                image_content = await file.read()
                if image_content:
                    import base64
                    img_b64 = base64.b64encode(image_content).decode("utf-8")
                    img_data_url = f"data:image/png;base64,{img_b64}"
                    # 追问附带上结构化场景数据
                    text = followup
                    if scene:
                        text = f"【画布当前结构数据】\n{scene}\n\n【用户问题】{followup}"
                    messages.append({"role": "user", "content": [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": img_data_url}},
                    ]})
                else:
                    messages.append({"role": "user", "content": followup})
            else:
                messages.append({"role": "user", "content": followup})
        else:
            if not file:
                return _stream_error("vision 模式需要上传画布截图")
            image_content = await file.read()
            if not image_content:
                return _stream_error("上传的图片为空")
            import base64
            img_b64 = base64.b64encode(image_content).decode("utf-8")
            img_data_url = f"data:image/png;base64,{img_b64}"
            if scene:
                prompt = f"""你是一个机械设计助手。请结合以下结构化数据（已将画布2D坐标映射为3D工程坐标）和图片，解读这张草图的设计内容。

{scene}

请从以下角度分析：
1. **整体结构**：图中画了什么样的几何体或形状组合？结合三维位置(X,Y,Z)分析空间堆叠关系——Z轴是垂直高度，不同组件的Z值差异代表它们在空间中的上下位置。
2. **设计意图**：这些元素可能构成什么装置或结构？根据具体尺寸、朝向和Z轴高度差推理。
3. **尺寸与比例**：给出关键尺寸和比例关系（数据已标注了各维度的尺寸，请直接引用）。
4. **设计建议**：如果要进一步细化设计，可以如何调整尺寸/位置/朝向？用X/Y/Z坐标给出具体调整建议。

用简洁专业的中文回答。分析中务必引用结构数据中的具体X/Y/Z坐标值和尺寸。"""
            else:
                prompt = """你是一个机械设计助手。请解读这张草图中的设计内容。

请从以下角度分析：
1. **整体结构**：图中画了什么样的几何体或形状组合？
2. **设计意图**：这些元素可能构成什么装置或结构？
3. **尺寸与比例**：关键尺寸和空间关系如何？
4. **建议**：如果要进一步细化设计，可以从哪些方面入手？

用简洁专业的中文回答，按上述四个方向分段。"""
            messages = [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": img_data_url}},
            ]}]

        from openai import OpenAI
        import queue

        async def stream():
            q = queue.Queue()
            def _run():
                try:
                    client = OpenAI(base_url=v_base_url, api_key=v_api_key)
                    resp = client.chat.completions.create(
                        model=v_model,
                        messages=messages,
                        stream=True,
                        temperature=0.3,
                    )
                    for chunk in resp:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            q.put(("token", delta.content))
                    q.put(("done", ""))
                except Exception as e:
                    q.put(("error", str(e)))

            asyncio.create_task(asyncio.to_thread(_run))
            while True:
                kind, content = await asyncio.to_thread(lambda: q.get())
                if kind == "done":
                    yield "data: " + json.dumps({"type": "done"}) + "\n"
                    break
                elif kind == "error":
                    yield "data: " + json.dumps({"type": "error", "content": content}) + "\n"
                    break
                else:
                    yield "data: " + json.dumps({"type": "token", "content": content}) + "\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    # === mode=structure (默认) ===
    if not scene and not followup:
        return _stream_error("scene 为空")

    if not api_key:
        return _stream_error("推理模型未配置 API Key,请在「设置 → 模型配置」中补全")

    prompt = f"""你是一个机械设计助手。请解读以下场景中的设计内容：

{scene}

请从以下角度分析：
1. **整体结构**：描述了什么样的几何体组合或布局？
2. **设计意图**：这些元素可能构成什么装置或结构？
3. **尺寸与比例**：关键尺寸和空间关系如何？
4. **建议**：如果要进一步细化设计，可以从哪些方面入手？

用简洁专业的中文回答，按上述四个方向分段。"""

    from openai import OpenAI
    import queue

    async def stream():
        q = queue.Queue()
        def _run():
            try:
                client = OpenAI(base_url=base_url, api_key=api_key)
                # 追问模式：构建多轮对话
                if followup:
                    messages = []
                    try:
                        hist = json.loads(history) if history else []
                        for m in hist:
                            messages.append({"role": m["role"], "content": m["content"]})
                    except Exception:
                        pass
                    messages.append({"role": "user", "content": followup})
                else:
                    messages = [{"role": "user", "content": prompt}]
                
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    temperature=0.3,
                )
                for chunk in resp:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        q.put(("token", delta.content))
                q.put(("done", ""))
            except Exception as e:
                q.put(("error", str(e)))

        asyncio.create_task(asyncio.to_thread(_run))
        while True:
            kind, content = await asyncio.to_thread(lambda: q.get())
            if kind == "done":
                yield "data: " + json.dumps({"type": "done"}) + "\n"
                break
            elif kind == "error":
                yield "data: " + json.dumps({"type": "error", "content": content}) + "\n"
                break
            else:
                yield "data: " + json.dumps({"type": "token", "content": content}) + "\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.on_event("startup")
def _startup():
    from .db import init_db
    init_db()

if __name__ == "__main__":
    import uvicorn
    _startup()
    uvicorn.run(app, host="0.0.0.0", port=8093)
