"""Authentication - JWT token verification for Anvil API.

认证/用户管理已分离到 AdminService(DesignTool 独立子模块,端口 8097)。
本模块只保留 token 校验:解析 JWT → 查 MySQL users 表(与 AdminService 共享库/secret)。

登录/注册/改密码/用户管理/登录日志 → AdminService:/api/auth/*, /api/admin/*
"""

import os
from jose import jwt, JWTError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .db import User, get_session

SECRET_KEY = os.environ.get("ANVIL_JWT_SECRET", "anvil-dev-secret-change-in-production")
ALGORITHM = "HS256"

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
        user = session.query(User).filter_by(id=user_id).first()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        if user.status != "active":
            raise HTTPException(status_code=403, detail="Account disabled")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
