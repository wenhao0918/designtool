"""POST /api/sketch — 手绘草图入口。

图片 + 结构化场景 → vision 识别 + CAD 原语 → agent 建模。
"""
import os
import json
import time
import httpx
from fastapi import APIRouter, Form, UploadFile, File, Depends

from anvil.deps import get_agent, user_projects_dir
from anvil.db import User
from anvil.auth import get_current_user
from anvil.sketch import sketch_to_message, scene_to_cad_instructions, scene_to_model_code

router = APIRouter()


@router.post("/api/sketch")
async def sketch(
    project: str = Form(...),
    file: UploadFile = File(...),
    message: str = Form(""),
    scene: str = Form(""),
    user: User = Depends(get_current_user),
):
    """手绘草图 → sketch-service 识别 + 结构化场景 → agent 建模。

    两条路径并行：
    1. PNG → vision 识别 → 语义文本
    2. scene JSON → CAD 原语 → FreeCAD STEP
    """
    agent = get_agent(project, user.username)
    if not agent:
        return {"error": "project not found"}

    content = await file.read()
    if not content:
        return {"error": "empty image"}

    # 路径 1：vision 识别（sketch-service）
    sketch_url = os.environ.get("SKETCH_SERVICE_URL", "http://localhost:8096")
    vision_msg = ""
    intent = {}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            files = {"file": (file.filename or "sketch.png", content, "image/png")}
            data = {"template": "mechanical"}
            if message:
                data["prompt"] = (
                    "你是机械设计工程师。用户一边画草图一边语音描述：\n"
                    f"{message}\n\n"
                    "请结合语音描述和草图，输出结构化设计意图 JSON："
                    '{"type": 零件类型, "dimensions": {参数: 值}, "features": [特征], '
                    '"description": 设计意图, "suggested_name": 英文零件名}'
                )
            resp = await client.post(f"{sketch_url}/recognize", files=files, data=data)
            payload = resp.json()
    except Exception as e:
        return {"error": f"sketch-service 调用失败: {e}"}

    if "result" in payload and "error" not in payload.get("result", {}):
        intent = payload["result"]
        vision_msg = sketch_to_message(intent)
        if message:
            vision_msg = f"[用户语音] {message}\n\n" + vision_msg
    elif "error" in payload.get("result", {}):
        vision_msg = f"[视觉识别不可用] {payload['result']['error']}"

    # 路径 2：结构化场景 → CAD 原语 → FreeCAD STEP
    cad_msg = ""
    step_files = []
    if scene:
        try:
            scene_data = json.loads(scene)
            cad_msg = scene_to_cad_instructions(scene_data)
        except (json.JSONDecodeError, Exception) as e:
            cad_msg = f"[场景解析失败] {e}"

        try:
            fc_code = scene_to_model_code(scene_data, output_name=f"sketch_{project}")
            if fc_code:
                result = agent.freecad.execute_python(fc_code, timeout=180)
                if result.get("files"):
                    step_files = [os.path.basename(f) for f in result["files"]]
                    cad_msg += f"\n\n✅ 已生成 STEP 模型：{', '.join(step_files)}"
                elif result.get("stderr"):
                    cad_msg += f"\n\n⚠️ FreeCAD 执行警告: {result['stderr'][:200]}"
        except Exception as e:
            cad_msg += f"\n\n⚠️ 模型生成失败: {e}"

    # 合并消息
    parts = []
    if cad_msg:
        parts.append(cad_msg)
    if vision_msg:
        parts.append(vision_msg)
    full_message = "\n\n".join(parts) if parts else "(空输入)"

    # 保存草图
    try:
        from anvil.deps import user_projects_dir
        upload_dir = os.path.join(user_projects_dir(user.username), project, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        sketch_path = os.path.join(upload_dir, "sketch_" + str(int(time.time())) + ".png")
        with open(sketch_path, "wb") as fout:
            fout.write(content)
    except Exception:
        pass

    return {"intent": intent, "message": full_message, "has_scene": bool(cad_msg), "steps": step_files}
