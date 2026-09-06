"""AdminService — DesignTool 管理服务(独立子模块)。

职责:
- 认证:登录 / 注册 / 修改密码 / me(签发 JWT,写登录日志)
- 用户管理:增删改查 / 角色分级(admin/engineer/viewer)/ 启停
- 日志:登录日志 / 系统日志(下载追溯 + 设计日志)

与 Anvil 解耦:
- 共享 MySQL anvil 库(users/login_logs 表)与 JWT secret
- Anvil 只保留 token 校验(get_current_user),不再承担认证/管理
- 通过 HTTP API(/api/auth/*, /api/admin/*)被前端访问

端口:8097(隧道同端口映射)
"""

import os
from datetime import datetime
from sqlalchemy import BigInteger, create_engine, Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# 用户分级
ROLE_ADMIN = "admin"
ROLE_ENGINEER = "engineer"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_ENGINEER, ROLE_VIEWER)

DEFAULT_MYSQL_URL = "mysql+pymysql://user:password@localhost:3306/anvil?charset=utf8mb4"
DB_URL = os.environ.get("ANVIL_DB_URL", DEFAULT_MYSQL_URL)

# 系统日志数据目录(与 Anvil 共享,读 downloads.jsonl + 各项目 .design/log)
DATA_DIR = os.environ.get("ANVIL_DATA_DIR", "")

engine = create_engine(DB_URL, echo=False, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    sys_user_id = Column(BigInteger, nullable=True, index=True)  # ruoyi sys_user.user_id 映射
    password_hash = Column(String(256), nullable=False)
    display_name = Column(String(128), default="")
    role = Column(String(32), default=ROLE_VIEWER, index=True)
    status = Column(String(16), default="active")
    # 测试用户:未自配模型时回退平台默认配置;非测试用户必须自配推理/视觉模型
    is_test = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LoginLog(Base):
    __tablename__ = "login_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), index=True)
    success = Column(Boolean, default=False)
    ip = Column(String(64), default="")
    user_agent = Column(String(256), default="")
    detail = Column(String(128), default="")
    time = Column(DateTime, default=datetime.utcnow)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    description = Column(String(255), default="")
    permissions = Column(Text, default="")


class ModelConfig(Base):
    __tablename__ = "model_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # inference / vision / voice
    base_url = Column(String(512), default="")
    api_key = Column(String(512), default="")
    model = Column(String(128), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Tool(Base):
    __tablename__ = "tools"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(String(255), default="")
    enabled = Column(Integer, default=1)


class RoleTool(Base):
    __tablename__ = "role_tools"
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_code = Column(String(32), nullable=False)
    tool_code = Column(String(64), nullable=False)


class UserTool(Base):
    __tablename__ = "user_tools"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    tool_code = Column(String(64), nullable=False)
    granted = Column(Integer, default=1)  # 1=额外授予 0=禁止


class TokenUsage(Base):
    __tablename__ = "token_usage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(64), default="")
    kind = Column(String(16), default="inference")
    model = Column(String(128), default="")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class PermissionRequest(Base):
    __tablename__ = "permission_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(64), nullable=False)
    tool_code = Column(String(64), nullable=False)
    reason = Column(String(255), default="")
    status = Column(String(16), default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(64), default="")


def _hash_password(password: str) -> str:
    import bcrypt
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def _verify_password(password: str, hash: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode(), hash.encode())
    except Exception:
        return False


def init_db():
    Base.metadata.create_all(engine)
    _ensure_user_is_test_col()


def _ensure_user_is_test_col():
    """幂等迁移:users 表补 is_test 列(与 Anvil 侧同构,重复执行无害)。"""
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    try:
        insp = sa_inspect(engine)
        if "is_test" in [c["name"] for c in insp.get_columns("users")]:
            return
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE users ADD COLUMN is_test BOOLEAN DEFAULT 0"))
        print("[db] users.is_test 列已补齐")
    except Exception as e:
        print(f"[db] users.is_test 迁移跳过: {e}")


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
