"""用户模型配置:推理(inference)/视觉(vision)/语音(voice)。

每个用户自设 API key/base_url/model,各工具(Anvil 设计 / 手绘识别 / 语音)统一读取。
- GET  /api/settings/model-config  读取自己的配置(返回三类;未设置返回空)
- PUT  /api/settings/model-config  保存自己的配置(按 kind upsert)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import User, ModelConfig, get_session
from auth import get_current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])

KINDS = ("inference", "vision", "voice")


class ModelConfigItem(BaseModel):
    kind: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class ModelConfigPut(BaseModel):
    inference: ModelConfigItem | None = None
    vision: ModelConfigItem | None = None
    voice: ModelConfigItem | None = None


@router.get("/model-config")
async def get_model_config(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    rows = session.query(ModelConfig).filter_by(user_id=user.id).all()
    result = {}
    for r in rows:
        result[r.kind] = {"base_url": r.base_url or "", "api_key": r.api_key or "", "model": r.model or ""}
    # 默认返回三类(缺省为空)
    for k in KINDS:
        result.setdefault(k, {"base_url": "", "api_key": "", "model": ""})
    return result


@router.put("/model-config")
async def put_model_config(req: ModelConfigPut, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    items = {"inference": req.inference, "vision": req.vision, "voice": req.voice}
    for kind, item in items.items():
        if item is None:
            continue
        row = session.query(ModelConfig).filter_by(user_id=user.id, kind=kind).first()
        if row is None:
            row = ModelConfig(user_id=user.id, kind=kind)
            session.add(row)
        row.base_url = (item.base_url or "").strip()
        row.api_key = (item.api_key or "").strip()
        row.model = (item.model or "").strip()
    session.commit()
    return {"success": True}


class BatchModelConfigItem(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class BatchModelConfigPut(BaseModel):
    usernames: list[str] | None = None   # 空/None = 全部用户
    inference: BatchModelConfigItem | None = None
    vision: BatchModelConfigItem | None = None
    voice: BatchModelConfigItem | None = None


@router.put("/model-config/batch")
async def put_model_config_batch(req: BatchModelConfigPut, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """管理员批量配置用户模型 key(测试用户统一配置)。

    usernames 为空则应用到全部用户。
    """
    from db import ROLES
    if (user.role or "user") != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="admin only")
    q = session.query(User)
    if req.usernames:
        q = q.filter(User.username.in_(req.usernames))
    users = q.all()
    items = {"inference": req.inference, "vision": req.vision, "voice": req.voice}
    applied = 0
    for u in users:
        for kind, item in items.items():
            if item is None:
                continue
            row = session.query(ModelConfig).filter_by(user_id=u.id, kind=kind).first()
            if row is None:
                row = ModelConfig(user_id=u.id, kind=kind)
                session.add(row)
            row.base_url = (item.base_url or "").strip()
            row.api_key = (item.api_key or "").strip()
            row.model = (item.model or "").strip()
        applied += 1
    session.commit()
    return {"success": True, "applied_users": applied}
