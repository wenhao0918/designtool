"""AdminService — FastAPI 入口(独立服务,端口 8097)。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth import router as auth_router
from admin import router as admin_router
from settings import router as settings_router
from tool_requests import router as requests_router
from db import init_db

app = FastAPI(title="AdminService")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(settings_router)
app.include_router(requests_router)


@app.on_event("startup")
def _startup():
    init_db()


# MCP 支持:把 AdminService 端点转成 MCP 工具,挂载 /mcp
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from mcp_helper import mount_mcp
    mount_mcp(app, name="AdminService", description="用户/角色/工具/配置管理")
except Exception as e:
    print("[mcp] AdminService MCP 挂载跳过:", e)
