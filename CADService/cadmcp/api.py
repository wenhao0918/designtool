"""CADService — FreeCAD 统一执行服务(端口 8102,HTTP + MCP 一体)。

前移自 /mnt/data/develop/mcp_servers(2026-08-26):
- FreeCAD 路线唯一;build123d(geom_mcp)终止
- HTTP: Anvil 等内部服务调用(快)
- /mcp: fastapi-mcp 自动暴露(SSE,AI 客户端/Dify 可接),未装时静默跳过

API:
  GET  /api/cad/health     FreeCAD 可用性
  POST /api/cad/execute    {code, work_dir?, timeout?} → {ok, files, stdout...}

启动: PYTHONPATH=/usr/lib/freecad-python3/lib python -m cadmcp.api --port 8102
"""

import argparse
import os
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .executor import execute, has_freecad

app = FastAPI(title="CADService", version="0.1.0",
              description="FreeCAD 统一执行层:脚本执行 + STEP/STL 导出")


class ExecuteReq(BaseModel):
    code: str
    work_dir: str = ""          # 空 → /tmp;建议传项目 cad 目录
    timeout: int = 120


@app.get("/api/cad/health", operation_id="health_check",
         summary="FreeCAD 可用性检查")
def health():
    return {"ok": True, "tool": "CADService",
            "has_freecad": has_freecad(),
            "platform": sys.platform}


@app.post("/api/cad/execute", operation_id="execute_freecad",
          summary="执行 FreeCAD Python 脚本并导出 STEP/STL",
          description="在 FreeCAD(Part API)中执行 Python 建模代码。"
                      "work_dir 限定项目数据区或 /tmp;产物 STEP/STL 落盘后返回文件清单。")
def execute_api(req: ExecuteReq):
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code 为空")
    # 安全:work_dir 限定在项目数据区或 /tmp(防任意路径写)
    wd = req.work_dir or "/tmp"
    real = os.path.realpath(wd)
    allowed_roots = (
        os.environ.get("ANVIL_DATA_DIR", "/mnt/data/develop/elderly-care-robot/DesignTool/Anvil/data"),
        "/tmp",
    )
    if not any(real == r or real.startswith(r + os.sep) for r in allowed_roots):
        raise HTTPException(status_code=403,
                            detail="work_dir 不在允许的数据目录内")
    return execute(req.code, work_dir=wd,
                   timeout=min(req.timeout, 600))


def main():
    import uvicorn
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    else:
        port = int(os.environ.get("CAD_PORT", "8102"))
    # MCP 挂载(可选)
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        from mcp_helper import mount_mcp
        mount_mcp(app, name="CADService",
                  description="FreeCAD 统一执行:建模脚本执行,STEP/STL 导出")
    except Exception as e:
        print("[mcp] CADService MCP 挂载跳过:", e)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
