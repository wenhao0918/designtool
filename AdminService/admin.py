"""AdminService 管理路由:用户管理 / 登录日志 / 系统日志(仅 admin)。"""

import os
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import User, LoginLog, Role, ModelConfig, Tool, RoleTool, UserTool, TokenUsage, PermissionRequest, get_session, _hash_password, ROLES, ROLE_VIEWER
from auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(user: User):
    if (user.role or "user") != "admin":
        raise HTTPException(status_code=403, detail="admin only")


class UserCreateRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = ROLE_VIEWER


class UserUpdateRequest(BaseModel):
    role: str | None = None
    status: str | None = None
    password: str | None = None
    display_name: str | None = None
    is_test: bool | None = None  # 测试用户开关:豁免"必须自配模型"策略


@router.get("/roles")
async def list_roles(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """角色表(仅 admin):code/name/description/permissions。"""
    _require_admin(user)
    roles = session.query(Role).order_by(Role.id).all()
    return [{
        "code": r.code,
        "name": r.name,
        "description": r.description,
        "permissions": r.permissions or "",
    } for r in roles]


@router.get("/tools")
async def list_tools(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """工具列表 + 角色授权 + 用户授权(仅 admin)。"""
    _require_admin(user)
    tools = session.query(Tool).order_by(Tool.id).all()
    role_tools = {(r.role_code, r.tool_code) for r in session.query(RoleTool).all()}
    user_tools = {(u.user_id, u.tool_code): u.granted for u in session.query(UserTool).all()}
    return {
        "tools": [{"code": t.code, "name": t.name, "description": t.description, "enabled": t.enabled} for t in tools],
        "role_tools": sorted([{"role_code": r, "tool_code": t} for r, t in role_tools], key=lambda x: (x["role_code"], x["tool_code"])),
        "user_tools": [{"user_id": uid, "tool_code": tc, "granted": g} for (uid, tc), g in user_tools.items()],
    }


class RoleToolPut(BaseModel):
    role_code: str
    tool_code: str
    granted: bool


@router.put("/tools/role")
async def set_role_tool(req: RoleToolPut, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """给角色授予/回收工具(仅 admin)。"""
    _require_admin(user)
    row = session.query(RoleTool).filter_by(role_code=req.role_code, tool_code=req.tool_code).first()
    if req.granted:
        if not row:
            session.add(RoleTool(role_code=req.role_code, tool_code=req.tool_code))
    else:
        if row:
            session.delete(row)
    session.commit()
    return {"success": True}


class UserToolPut(BaseModel):
    user_id: int
    tool_code: str
    granted: bool  # True=额外授予 False=禁止


@router.put("/tools/user")
async def set_user_tool(req: UserToolPut, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """给用户个别授予/禁止工具(仅 admin)。"""
    _require_admin(user)
    row = session.query(UserTool).filter_by(user_id=req.user_id, tool_code=req.tool_code).first()
    if not row:
        row = UserTool(user_id=req.user_id, tool_code=req.tool_code, granted=1)
        session.add(row)
    row.granted = 1 if req.granted else 0
    session.commit()
    return {"success": True}


@router.get("/users")
async def list_users(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_admin(user)
    users = session.query(User).order_by(User.id).all()
    return [{
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "status": u.status,
        "is_test": bool(getattr(u, "is_test", False)),
        "created_at": u.created_at.isoformat() if u.created_at else "",
    } for u in users]


@router.post("/users")
async def create_user(req: UserCreateRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_admin(user)
    uname = req.username.strip()
    if not uname or session.query(User).filter_by(username=uname).first():
        raise HTTPException(status_code=400, detail="用户名无效或已存在")
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail="角色无效: " + ",".join(ROLES))
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="密码至少4位")
    u = User(
        username=uname,
        password_hash=_hash_password(req.password),
        display_name=req.display_name.strip() or uname,
        role=req.role,
    )
    session.add(u)
    session.commit()
    return {"success": True, "id": u.id, "username": u.username, "role": u.role}


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UserUpdateRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_admin(user)
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if req.role is not None:
        if req.role not in ROLES:
            raise HTTPException(status_code=400, detail="角色无效")
        target.role = req.role
    if req.status is not None:
        if req.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="状态无效")
        target.status = req.status
    if req.password:
        if len(req.password) < 4:
            raise HTTPException(status_code=400, detail="密码至少4位")
        target.password_hash = _hash_password(req.password)
    if req.display_name is not None:
        target.display_name = req.display_name.strip()
    if req.is_test is not None:
        target.is_test = bool(req.is_test)
    session.commit()
    return {"success": True, "id": target.id, "username": target.username, "role": target.role, "status": target.status}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    target = session.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    session.delete(target)
    session.commit()
    return {"success": True, "deleted": target.username}


@router.get("/requests")
async def list_requests(user: User = Depends(get_current_user), session: Session = Depends(get_session), status: str = "pending"):
    """工具权限申请列表(仅 admin)。status: pending/approved/rejected/all。"""
    _require_admin(user)
    q = session.query(PermissionRequest)
    if status != "all":
        q = q.filter(PermissionRequest.status == status)
    rows = q.order_by(PermissionRequest.id.desc()).limit(200).all()
    return [{
        "id": r.id,
        "username": r.username,
        "tool_code": r.tool_code,
        "reason": r.reason,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "reviewed_by": r.reviewed_by or "",
    } for r in rows]


@router.post("/requests/{req_id}/approve")
async def approve_request(req_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """审批通过 → 写 user_tools(granted=1)完成授权。"""
    _require_admin(user)
    from datetime import datetime as _dt
    r = session.query(PermissionRequest).filter_by(id=req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="request not found")
    if r.status != "pending":
        raise HTTPException(status_code=400, detail="already " + r.status)
    r.status = "approved"
    r.reviewed_at = _dt.utcnow()
    r.reviewed_by = user.username
    ut = session.query(UserTool).filter_by(user_id=r.user_id, tool_code=r.tool_code).first()
    if not ut:
        ut = UserTool(user_id=r.user_id, tool_code=r.tool_code, granted=1)
        session.add(ut)
    else:
        ut.granted = 1
    session.commit()
    return {"success": True, "username": r.username, "tool_code": r.tool_code, "status": "approved"}


@router.post("/requests/{req_id}/reject")
async def reject_request(req_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """审批拒绝。"""
    _require_admin(user)
    from datetime import datetime as _dt
    r = session.query(PermissionRequest).filter_by(id=req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="request not found")
    if r.status != "pending":
        raise HTTPException(status_code=400, detail="already " + r.status)
    r.status = "rejected"
    r.reviewed_at = _dt.utcnow()
    r.reviewed_by = user.username
    session.commit()
    return {"success": True, "username": r.username, "tool_code": r.tool_code, "status": "rejected"}


@router.get("/token-usage")
async def token_usage(user: User = Depends(get_current_user), session: Session = Depends(get_session), days: int = 7):
    """token 消耗统计(仅 admin):按用户/类型汇总。"""
    _require_admin(user)
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(days=days)
    rows = session.query(TokenUsage).filter(TokenUsage.created_at >= since).all()
    by_user = {}
    by_kind = {}
    total = 0
    for r in rows:
        u = by_user.setdefault(r.username or str(r.user_id), {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        u["prompt"] += r.prompt_tokens or 0
        u["completion"] += r.completion_tokens or 0
        u["total"] += r.total_tokens or 0
        u["calls"] += 1
        k = by_kind.setdefault(r.kind, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        k["prompt"] += r.prompt_tokens or 0
        k["completion"] += r.completion_tokens or 0
        k["total"] += r.total_tokens or 0
        k["calls"] += 1
        total += r.total_tokens or 0
    return {
        "days": days,
        "total_tokens": total,
        "by_user": [{"username": k, **v} for k, v in sorted(by_user.items(), key=lambda x: -x[1]["total"])],
        "by_kind": [{"kind": k, **v} for k, v in sorted(by_kind.items(), key=lambda x: -x[1]["total"])],
    }


@router.get("/login-logs")
async def login_logs(user: User = Depends(get_current_user), session: Session = Depends(get_session), limit: int = 200):
    _require_admin(user)
    logs = session.query(LoginLog).order_by(LoginLog.id.desc()).limit(min(limit, 500)).all()
    return [{
        "id": l.id,
        "username": l.username,
        "success": l.success,
        "ip": l.ip,
        "user_agent": l.user_agent,
        "detail": l.detail,
        "time": l.time.isoformat() if l.time else "",
    } for l in logs]


@router.get("/logs")
async def system_logs(user: User = Depends(get_current_user)):
    """系统日志:下载追溯(downloads.jsonl)+ 各用户项目设计日志(.design/log)。

    读取 ANVIL_DATA_DIR(与 Anvil 共享数据目录)。
    """
    _require_admin(user)
    data_dir = os.environ.get("ANVIL_DATA_DIR", "")
    downloads = []
    dlog = os.path.join(data_dir, "downloads.jsonl")
    if os.path.exists(dlog):
        for line in open(dlog, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                downloads.append(json.loads(line))
            except Exception:
                pass

    design = []
    proj_root = os.path.join(data_dir, "projects")
    if os.path.isdir(proj_root):
        for uname in sorted(os.listdir(proj_root)):
            udir = os.path.join(proj_root, uname)
            if not os.path.isdir(udir):
                continue
            for dname in sorted(os.listdir(udir)):
                logf = os.path.join(udir, dname, ".design", "log")
                if not os.path.isfile(logf):
                    continue
                # 项目内序号 = 文件行号(1-based),追加式日志行号稳定,
                # 设计者可用它指定"从第 N 步重新设计"。
                seq = 0
                for line in open(logf, encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    seq += 1
                    design.append({
                        "seq": seq,
                        "id": e.get("id", ""),
                        "time": e.get("time", ""),
                        "username": uname,
                        "project": dname,
                        "action": e.get("action", ""),
                        "instruction": e.get("instruction", ""),
                        "llm_response": e.get("llm_response", "")[:200],
                        "output_dir": e.get("output_dir", ""),
                    })
    downloads.sort(key=lambda x: x.get("time", ""), reverse=True)
    design.sort(key=lambda x: x.get("time", ""), reverse=True)
    return {"downloads": downloads[:500], "design": design[:500]}
