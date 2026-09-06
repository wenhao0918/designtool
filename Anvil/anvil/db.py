"""Database - SQLAlchemy engine + models for Anvil.

Backend: MySQL (ssh 3307, db=anvil), fallback SQLite for local dev.
Tables:
  users:      id, username, password_hash, display_name, role, status, created_at, updated_at
  login_logs: id, username, success, ip, user_agent, detail, time
  projects:   id, name, display_name, description, user_id, phase, path, created_at
"""

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Text, BigInteger
from sqlalchemy import text as sqlalchemy_text
from sqlalchemy.orm import declarative_base, sessionmaker

# 用户分级:admin=管理员(全部权限+管理入口) / engineer=工程师(设计) / viewer=访客(只读)
ROLE_ADMIN = "admin"
ROLE_ENGINEER = "engineer"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_ENGINEER, ROLE_VIEWER)

DB_DIR = os.environ.get("ANVIL_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

# MySQL 优先(生产):ANVIL_DB_URL 可覆盖;连不上则回退 SQLite(本地开发/兜底)
DEFAULT_MYSQL_URL = "mysql+pymysql://user:password@localhost:3306/anvil?charset=utf8mb4"
DB_URL = os.environ.get("ANVIL_DB_URL", DEFAULT_MYSQL_URL)
SQLITE_PATH = os.path.join(DB_DIR, "anvil.db")
os.makedirs(DB_DIR, exist_ok=True)

# 数据库连不上直接报错,不回退 SQLite(用户决策 2026-09-03)
engine = create_engine(DB_URL, echo=False, pool_pre_ping=True, pool_recycle=3600)
with engine.connect() as conn:
    conn.execute(sqlalchemy_text("SELECT 1"))
_BACKEND = "mysql"

SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


class User(Base):
    """本地用户映射缓存——凭据权威在 ruoyi-cloud-plus(sys_user),本地不存口令。

    sys_user_id: ruoyi sys_user.user_id(商用对接时业务数据以此为准);
    对齐 ruoyi 多租户: tenant_id。
    """
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)  # 恒为 "!",凭据走 ruoyi
    sys_user_id = Column(BigInteger, nullable=True, index=True)  # ruoyi sys_user.user_id
    tenant_id = Column(String(20), default="000000", index=True)
    display_name = Column(String(128), default="")
    role = Column(String(32), default=ROLE_VIEWER, index=True)
    status = Column(String(16), default="active")  # active / disabled
    # 测试用户:未自配模型时回退 .env 全局默认;非测试用户必须自配推理/视觉模型才能用 AI 工具
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


class ProjectDB(Base):
    """对齐 ruoyi-cloud-plus 多租户结构(tenant_id + 审计四件 + del_flag)。"""
    __tablename__ = "projects"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(20), default="000000", index=True)   # 租户
    name = Column(String(128), nullable=False, index=True)
    parent_id = Column(BigInteger, ForeignKey("projects.id"), nullable=True, index=True)
    display_name = Column(String(256), default="")
    description = Column(Text, default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    phase = Column(String(32), default="concept")
    path = Column(String(512), nullable=False)
    # ruoyi-cloud-plus 审计字段(对齐 TenantEntity: 租户 + 审计五件 + del_flag)
    create_dept = Column(BigInteger, nullable=True)
    create_by = Column(BigInteger, nullable=True)   # 商用时= sys_user.user_id
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, nullable=True)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    del_flag = Column(String(1), default="0")  # ruoyi 约定:0存在 2删除(软删)


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


class Share(Base):
    """项目共享授权(对齐 ruoyi TenantEntity: 租户 + 审计五件 + del_flag)。"""
    __tablename__ = "shares"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(20), default="000000", index=True)   # 租户编号
    # 业务字段(owner_id/target_id 商用迁移时映射 sys_user_id)
    owner_id = Column(Integer, nullable=False, index=True)
    project_id = Column(BigInteger, nullable=False, index=True)  # FK→projects.id(项目身份统一 bigint)
    target_id = Column(Integer, nullable=False, index=True)
    permission = Column(String(16), default="read")  # read / comment / edit
    # ruoyi 审计字段
    create_dept = Column(BigInteger, nullable=True)
    create_by = Column(BigInteger, nullable=True)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, nullable=True)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    del_flag = Column(String(1), default="0")  # 0存在 2删除(软删)


class DltqLedgerRow(Base):
    """dltQ 账本(全需求矩阵 Q)——每项目一行,entries 为 JSON blob。

    - seq: 加法器递增项当前值(整数行号,永不复用;重置不归零、快照重载不回退)
    - entries: 全需求矩阵 JSON 数组([{seq,dltq,source,echo,executed,result}...])
    项目身份统一用 projects.id(bigint);CAD 产物等二进制仍落文件工作区。
    """
    __tablename__ = "dltq_ledger"
    project_id = Column(BigInteger, primary_key=True)  # FK→projects.id
    seq = Column(BigInteger, default=0, nullable=False)
    entries = Column(Text, default="[]")               # JSON blob(全需求矩阵)
    # ruoyi 审计字段(对齐 TenantEntity;账本为项目级状态行)
    tenant_id = Column(String(20), default="000000", index=True)
    create_dept = Column(BigInteger, nullable=True)
    create_by = Column(BigInteger, nullable=True)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, nullable=True)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TokenUsage(Base):
    __tablename__ = "token_usage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(64), default="")
    kind = Column(String(16), default="inference")  # inference / vision / voice
    model = Column(String(128), default="")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MechTerm(Base):
    """机械设计术语表——用户可自助增改,Anvil 建模时查询。
    
    支持同义词/别名机制：
    - 主术语(term): 存储定义的术语
    - 别名(aliases): 逗号分隔的同义词,查询时自动解析到主术语
    - 查询"盲孔"或"通孔"都返回同一条定义
    """
    __tablename__ = "mech_terms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    term = Column(String(64), unique=True, nullable=False, index=True)
    aliases = Column(Text, default="")  # 别名,逗号分隔(如 "盲孔,blind hole")
    definition = Column(Text, default="")
    geometry = Column(Text, default="")
    modeling = Column(Text, default="")
    application = Column(Text, default="")  # 应用场景
    distinction = Column(Text, default="")  # 与其他术语的区别
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ===== 已知结构知识库 ORM 模型（5 表，参照 MechTerm 模式）=====

class StructureTemplate(Base):
    """结构模板表——已知结构的顶层定义（= 高层术语具名块）。
    aliases/enum_values/expand_template 用 Text 存 JSON，应用层 json.loads/dumps。
    """
    __tablename__ = "structure_template"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    aliases = Column(Text, default="")          # JSON: ["储油罐","立式罐"]
    category = Column(String(64), default="")
    subcategory = Column(String(64), default="")
    description = Column(Text, default="")
    standard_ref = Column(String(128), default="")
    applicable_scope = Column(Text, default="")
    rag_dataset_id = Column(String(64), default="")
    expand_template = Column(Text, default="")  # JSON: 术语块展开运算模板
    status = Column(Integer, default=0)          # 0=启用 1=退役
    create_by = Column(BigInteger, default=None)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, default=None)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_dept = Column(BigInteger, default=None)
    tenant_id = Column(String(20), default="000000")


class StructureComponent(Base):
    """结构组件表——组件清单，支持嵌套递归（parent_id 自引用）。"""
    __tablename__ = "structure_component"
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, nullable=False, index=True)
    parent_id = Column(Integer, default=None, index=True)
    name = Column(String(128), nullable=False)
    component_type = Column(String(32), nullable=False)  # sub_structure/standard_part/custom_part/geometry
    ref_template_id = Column(Integer, default=None)
    ref_part_category = Column(String(64), default="")
    quantity_expr = Column(String(64), default="1")
    required = Column(Integer, default=1)  # 1=必需 0=可选
    sort_order = Column(Integer, default=0)
    principle_note = Column(Text, default="")
    create_by = Column(BigInteger, default=None)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, default=None)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_dept = Column(BigInteger, default=None)
    tenant_id = Column(String(20), default="000000")


class StructureParamDef(Base):
    """结构参数定义表——含计算公式（formula_expr）。"""
    __tablename__ = "structure_param_def"
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, nullable=False, index=True)
    param_key = Column(String(64), nullable=False)
    param_label = Column(String(64), default="")
    param_type = Column(String(32), default="string")  # float/int/string/enum/formula
    unit = Column(String(32), default="")
    required = Column(Integer, default=1)
    default_value = Column(String(128), default="")
    enum_values = Column(Text, default="")  # JSON: ["Q345R","Q235B"]
    validation_rule = Column(Text, default="")
    formula_expr = Column(Text, default="")
    formula_refs = Column(Text, default="")  # JSON: ["design_pressure","diameter"]
    sort_order = Column(Integer, default=0)
    create_by = Column(BigInteger, default=None)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, default=None)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_dept = Column(BigInteger, default=None)
    tenant_id = Column(String(20), default="000000")


class StructureConstraint(Base):
    """结构约束规则表——连接 C 约束场，提供约束规则来源。"""
    __tablename__ = "structure_constraint"
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, nullable=False, index=True)
    constraint_layer = Column(String(32), default="P")  # P硬律/M可行/V价值/C_c条件
    target_component = Column(String(128), default="")
    rule_type = Column(String(32), default="")
    description = Column(Text, nullable=False)
    standard_clause = Column(String(128), default="")
    formula_expr = Column(Text, default="")
    rag_chunk_tags = Column(Text, default="")  # JSON: ["GB150","壁厚"]
    severity = Column(String(16), default="hard")  # hard/soft
    sort_order = Column(Integer, default=0)
    create_by = Column(BigInteger, default=None)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, default=None)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_dept = Column(BigInteger, default=None)
    tenant_id = Column(String(20), default="000000")


class StructureAssemblyRule(Base):
    """装配规则表——组件之间的连接关系（机械原理的核心）。"""
    __tablename__ = "structure_assembly_rule"
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, nullable=False, index=True)
    from_component = Column(String(128), nullable=False)
    to_component = Column(String(128), nullable=False)
    connection_type = Column(String(32), default="")  # weld/flange/bolt/contact/insert/relative_pos
    relation_expr = Column(Text, default="")
    principle_note = Column(Text, default="")
    constraint_note = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    create_by = Column(BigInteger, default=None)
    create_time = Column(DateTime, default=datetime.utcnow)
    update_by = Column(BigInteger, default=None)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    create_dept = Column(BigInteger, default=None)
    tenant_id = Column(String(20), default="000000")


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


def _ensure_user_is_test_col():
    """幂等迁移:users 表补 is_test 列(MySQL/SQLite 通用,重复执行无害)。"""
    from sqlalchemy import inspect as sa_inspect
    try:
        insp = sa_inspect(engine)
        if "is_test" in [c["name"] for c in insp.get_columns("users")]:
            return
        with engine.begin() as conn:
            conn.execute(sqlalchemy_text(
                "ALTER TABLE users ADD COLUMN is_test BOOLEAN DEFAULT 0"
            ))
        print("[db] users.is_test 列已补齐")
    except Exception as e:
        # 列已存在(并发/方言差异)等场景静默
        print(f"[db] users.is_test 迁移跳过: {e}")


def init_db():
    """Create all tables and seed default admin user."""
    Base.metadata.create_all(engine)
    _ensure_user_is_test_col()
    session = SessionLocal()
    try:
        if not session.query(User).filter_by(username="admin").first():
            admin = User(
                username="admin",
                password_hash=_hash_password("anvil123"),
                display_name="管理员",
                role=ROLE_ADMIN,
            )
            session.add(admin)
            session.commit()
            print("Default admin user created: admin / anvil123")
        # 迁移旧角色:user → engineer
        for u in session.query(User).filter(User.role.in_(["user"])).all():
            u.role = ROLE_ENGINEER
        session.commit()
    finally:
        session.close()


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
