"""POST /api/scene/generate — MCP 入口。

纯 scene JSON → FreeCAD 生成 STEP。不需要 PNG、不需要 vision 模型。
"""
import os
import time
from fastapi import APIRouter, Depends

from anvil.deps import get_agent
from anvil.db import User
from anvil.auth import get_current_user
from anvil.sketch import scene_to_model_code, scene_to_parts

router = APIRouter()


@router.post("/api/scene/generate")
async def scene_generate(req: dict, user: User = Depends(get_current_user)):
    """MCP 入口：纯 scene JSON → FreeCAD 生成 STEP。

    请求体: {"project": "xxx", "scene": {"components": [...]}, "output_name": "optional"}

    AI 可直接传结构化场景，后端生成 STEP 并返回文件列表。
    """
    project = req.get("project", "default")
    scene_data = req.get("scene", {})
    output_name = req.get("output_name", f"scene_{int(time.time())}")

    agent = get_agent(project, user.username)
    if not agent:
        return {"error": "project not found"}

    parts = scene_to_parts(scene_data)
    if not parts:
        return {"error": "no valid components in scene", "parts_count": 0}

    fc_code = scene_to_model_code(scene_data, output_name=output_name)
    if not fc_code:
        return {"error": "failed to generate FreeCAD code"}

    try:
        result = agent.freecad.execute_python(fc_code, timeout=180)
    except Exception as e:
        return {"error": f"FreeCAD execution failed: {e}"}

    step_files = []
    if result.get("files"):
        step_files = [os.path.basename(f) for f in result["files"]]

    return {
        "status": result.get("status", "ok"),
        "steps": step_files,
        "parts_count": len(parts),
        "message": f"Generated {len(parts)} parts → {len(step_files)} files",
        "stdout": result.get("stdout", "")[:500],
        "stderr": result.get("stderr", "")[:500],
    }
