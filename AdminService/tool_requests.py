"""工具权限申请与审批。

- 用户申请:POST /api/requests(申请某工具,带理由)
- 用户查看:GET  /api/requests(自己的申请列表)
- 管理员审批:GET /api/admin/requests(待审/全部), POST /api/admin/requests/{id}/approve|reject
审批通过 → 写 user_tools(granted=1)完成授权。
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import User, Tool, UserTool, get_session, ROLE_ADMIN
from auth import get_current_user

router = APIRouter(prefix="/api", tags=["requests"])


class RequestCreate(BaseModel):
    tool_code: str
    reason: str = ""


def _req_dict(r) -> dict:
    return {
        "id": r.id,
        "username": r.username,
        "tool_code": r.tool_code,
        "reason": r.reason,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else "",
        "reviewed_by": r.reviewed_by or "",
    }


@router.post("/requests")
def create_request(req: RequestCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """用户申请工具权限。"""
    from db import PermissionRequest
    tool = session.query(Tool).filter_by(code=req.tool_code).first()
    if not tool:
        raise HTTPException(status_code=404, detail="tool not found")
    # 已有授权则无需申请
    existing = session.query(UserTool).filter_by(user_id=user.id, tool_code=req.tool_code).first()
    if existing and existing.granted == 1:
        return {"success": True, "already": True, "status": "approved"}
    # 已有 pending 申请
    dup = session.query(PermissionRequest).filter_by(user_id=user.id, tool_code=req.tool_code, status="pending").first()
    if dup:
        return {"success": True, "already": True, "status": "pending"}
    r = PermissionRequest(
        user_id=user.id,
        username=user.username,
        tool_code=req.tool_code,
        reason=(req.reason or "")[:255],
        status="pending",
        created_at=datetime.utcnow(),
    )
    session.add(r)
    session.commit()
    return {"success": True, "already": False, "status": "pending", "id": r.id}


@router.get("/requests")
def my_requests(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """我的申请列表。"""
    from db import PermissionRequest
    rows = session.query(PermissionRequest).filter_by(user_id=user.id).order_by(PermissionRequest.id.desc()).all()
    return [_req_dict(r) for r in rows]
