"""SketchService — FastAPI 绘图识别微服务 (:8096)

接收前端上传的 PNG + 场景描述 → vision 模型 → 结构化设计意图 JSON
独立于 Anvil，可通过 HTTP 调用。
"""

import io
import json
import os

from fastapi import FastAPI, UploadFile, File, Form
from recognize import recognize_sketch

app = FastAPI(title="SketchService")


@app.post("/recognize")
async def recognize(
    file: UploadFile = File(...),
    template: str = Form("mechanical"),
    prompt: str = Form(""),
):
    """识别手绘草图，返回结构化设计意图。"""
    content = await file.read()
    if not content:
        return {"result": {"error": "empty image"}}

    scene_text = prompt if prompt else ""
    result = recognize_sketch(content, scene_text)
    return {"result": result}


@app.get("/health")
async def health():
    return {"status": "ok"}


# MCP 支持:把 SketchService 端点转成 MCP 工具,挂载 /mcp
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from mcp_helper import mount_mcp
    mount_mcp(app, name="SketchService", description="手绘草图识别(vision 模型 → 设计意图)")
except Exception as e:
    print("[mcp] SketchService MCP 挂载跳过:", e)
