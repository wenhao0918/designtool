"""AdminService 认证路由:登录 / 注册 / 修改密码 / me。

登录成功/失败写 login_logs(登录日志)。
JWT secret 与 Anvil 共享(ANVIL_JWT_SECRET),Anvil 用同一 secret 校验 token。
"""

import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import User, LoginLog, get_session, _hash_password, _verify_password, ROLE_VIEWER

SECRET_KEY = os.environ.get("ANVIL_JWT_SECRET", "anvil-dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _log_login(session: Session, username: str, success: bool, request: Request, detail: str = ""):
    try:
        session.add(LoginLog(
            username=username,
            success=success,
            ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent", "") or "")[:256],
            detail=detail,
            time=datetime.utcnow(),
        ))
        session.commit()
    except Exception:
        pass


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


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


def user_payload(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "display_name": u.display_name}


@router.post("/login")
def login(req: LoginRequest, request: Request, session: Session = Depends(get_session)):
    user = session.query(User).filter_by(username=req.username).first()
    # 统一认证源:ruoyi-cloud-plus Auth(9210)——唯一凭据校验,
    # 复用 SampleClient(加密登录协议,不重新实现)。
    # 本地 users 表仅作映射缓存(sys_user_id/角色),不再保存口令语义。
    ok = False
    ruoyi_user_id = None
    _nick = req.username
    try:
        import sys as _sys
        _rt = str(__import__("pathlib").Path(__file__).resolve().parents[1])
        if _rt not in _sys.path:
            _sys.path.insert(0, _rt)
        from utils.matNgineClient import MatNgineClient as SampleClient
        _rc = SampleClient(host="127.0.0.1", port="8080",
                             username=req.username, password=req.password,
                             clientId=os.environ.get("MN_AUTH_CLIENT_ID", ""))
        ok, _resp = _rc.login()
        if ok:
            # 拉真实 userId/昵称(getInfo,带 token)
            try:
                _gi = _rc.get("/system/user/getInfo", {})
                _d = (_gi[1] if isinstance(_gi, tuple) else _gi)
                _user = (_d or {}).get("user") or {}
                ruoyi_user_id = _user.get("userId")
                _nick = _user.get("nickName") or req.username
            except Exception:
                pass
            # 映射行:首登建档——Anvil 角色映射(ruoyi admin→admin,其余→engineer);已存在保留原角色
            if not user:
                user = User(username=req.username, password_hash="!",
                            display_name=_nick, role=("admin" if req.username == "admin" else "engineer"), status="active")
                session.add(user)
            user.password_hash = "!"  # 统一源:本地不再存可用口令
            user.display_name = _nick
            if ruoyi_user_id:
                user.sys_user_id = int(ruoyi_user_id)
            session.commit()
    except ImportError:
        pass  # matngineapi 缺失(部署异常)→ 一律 401
    if not ok:
        _log_login(session, req.username, False, request, "ruoyi 认证失败")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.status != "active":
        _log_login(session, req.username, False, request, "账号已停用")
        raise HTTPException(status_code=403, detail="Account disabled")
    _log_login(session, req.username, True, request, "登录成功")
    return {"token": create_token(user), "user": user_payload(user)}


@router.post("/register")
def register(req: RegisterRequest, request: Request, session: Session = Depends(get_session)):
    """注册代理:统一走 ruoyi-cloud-plus(/auth/register,加密协议)。
    本地不再自建账号;注册成功后即可用该账号登录(首登建映射)。
    """
    uname = req.username.strip()
    if not uname or len(uname) < 2:
        raise HTTPException(status_code=400, detail="用户名至少2位")
    if len(req.password) < 6 or len(req.password) > 20:
        raise HTTPException(status_code=400, detail="密码6-20位")
    try:
        import sys as _sys, json as _json, base64 as _b64
        _rt = str(__import__("pathlib").Path(__file__).resolve().parents[1])
        if _rt not in _sys.path:
            _sys.path.insert(0, _rt)
        from utils.matNgineClient import RuoyiClient as AuthClient
        key = AuthClient.generateRandomString()
        enc_key = AuthClient.encrpt(_b64.b64encode(key.encode()).decode(),
                                     "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAKoR8mX0rGKLqzcWmOzbfj64K8ZIgOdHnzkXSOVOZbFu/TJhZ7rFAN+eaGkl3C4buccQd/EjEsj9ir7ijT7h96MCAwEAAQ==")
        headers = {"Content-Type": "application/json;charset=UTF-8",
                   "isToken": "false", "encrypt-key": enc_key, "isEncrypt": "true"}
        data = {"username": uname, "password": req.password,
                "tenantId": "000000",
                "clientId": os.environ.get("MN_AUTH_CLIENT_ID", ""),
                "grantType": "password",
                "userType": "sys_user"}
        body = AuthClient.aesEncrypt(_json.dumps(data), key)
        resp = AuthClient().post("http://127.0.0.1:8080/auth/register",
                                  body, headers)
        import json as _j
        r = _j.loads(resp.text)
        if r.get("code") != 200:
            raise HTTPException(status_code=400, detail=r.get("msg") or "注册失败")
        return {"success": True, "message": "注册成功,请登录"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail="注册通道不可用: %s" % str(e)[:120])

@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not _verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="新密码至少4位")
    user.password_hash = _hash_password(req.new_password)
    session.commit()
    return {"success": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_payload(user)


@router.get("/tools")
def my_tools(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """当前用户可用的工具列表(工具授权)。

    计算:admin 全部;否则 = 角色默认(role_tools)+ 用户额外授予(user_tools.granted=1)
    - 用户禁止(user_tools.granted=0)。
    """
    from db import Tool, RoleTool, UserTool
    if user.role == "admin":
        tools = session.query(Tool).filter_by(enabled=1).all()
        return {"tools": [{"code": t.code, "name": t.name, "description": t.description} for t in tools]}
    role_codes = {user.role}
    role_defaults = {rt.tool_code for rt in session.query(RoleTool).filter(RoleTool.role_code.in_(role_codes)).all()}
    extra = {ut.tool_code for ut in session.query(UserTool).filter_by(user_id=user.id, granted=1).all()}
    banned = {ut.tool_code for ut in session.query(UserTool).filter_by(user_id=user.id, granted=0).all()}
    allowed = (role_defaults | extra) - banned
    tools = session.query(Tool).filter(Tool.code.in_(allowed), Tool.enabled == 1).all()
    return {"tools": [{"code": t.code, "name": t.name, "description": t.description} for t in tools]}
