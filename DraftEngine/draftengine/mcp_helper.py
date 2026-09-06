"""通用 MCP 挂载助手——给 DesignTool 各 FastAPI 服务加 MCP 支持。

用法(在每个服务入口文件末尾):
    from mcp_helper import mount_mcp
    mount_mcp(app, name="服务名", description="描述")

挂载后:
- HTTP API 保持不变
- MCP 端点在 /mcp(SSE),fastapi-mcp 自动把 FastAPI 端点转成 MCP 工具
- fastapi-mcp 未安装时静默跳过(MCP 不可用但 HTTP 正常)

注意:fastapi-mcp 需装在运行该服务的 Python 环境。
"""

from fastapi import FastAPI


def mount_mcp(app: FastAPI, name: str = "", description: str = "", mount_path: str = "/mcp") -> bool:
    """把 FastAPI 端点自动转成 MCP 工具,挂载到 mount_path。

    返回 True=挂载成功, False=fastapi-mcp 不可用(静默跳过)。
    """
    try:
        from fastapi_mcp import FastApiMCP

        mcp = FastApiMCP(
            app,
            name=name or app.title or "FastAPI Service",
            description=description or app.description or "",
        )
        mcp.mount(mount_path=mount_path)
        return True
    except Exception as e:
        print("[mcp_helper] fastapi-mcp 不可用,MCP 未挂载(HTTP 正常): {}".format(e))
        return False
