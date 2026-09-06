"""sketch-service FastAPI — 通用图片语义解读微服务

本质: 图 + 用户提示词 → AI 按提示词解读 → 结构化结果
通用工具，不预设领域（涂鸦/漫画/数学/机械/电路...由提示词决定）。

端点:
  GET  /health        健康检查
  POST /recognize     图片 + 可选 prompt → 结构化解读 JSON
  GET  /prompts       列出内置提示词模板（可选）
"""

import os
import time
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException

from recognizer import recognize_image

app = FastAPI(title="sketch-service", version="2.0.0")

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"

# 内置提示词模板（用户可自定义传入，这里是常用场景示例）
PROMPT_TEMPLATES = {
    "general": "请仔细解读这张图片，理解它的内容和意图，然后输出结构化的描述。输出JSON：{\"summary\": \"简要总结\", \"elements\": [\"主要元素\"], \"details\": {\"关键属性\": \"值\"}, \"intent\": \"意图推测\"}",
    "mechanical": "你是机械设计工程师，解读这张手绘机械草图。识别：零件类型、关键尺寸、结构特征、可能用途。输出JSON：{\"type\": \"零件类型\", \"dimensions\": {\"参数\": \"值\"}, \"features\": [\"特征\"], \"description\": \"设计意图描述\", \"suggested_name\": \"建议英文零件名\"}",
    "sketch_to_3d": "这是手绘3D概念草图。请识别立体结构：基本体组合、空间关系、比例。输出JSON：{\"primitives\": [{\"type\": \"基本体\", \"position\": \"位置关系\", \"size\": \"相对尺寸\"}], \"assembly\": \"组合描述\", \"notes\": \"建模建议\"}",
    "mathematical": "这是手写数学内容。请识别公式或推导，转录为 LaTeX 并解释。输出JSON：{\"latex\": \"公式LaTeX\", \"explanation\": \"含义解释\", \"steps\": [\"推导步骤\"]}",
    "drawing": "这是儿童涂鸦/绘画。请描述画面内容和创意。输出JSON：{\"description\": \"画面描述\", \"objects\": [\"画了什么\"], \"mood\": \"氛围/情绪\", \"story\": \"可能的故事情节\"}",
    "comic": "这是漫画分镜。请识别：角色、动作、对白、情绪。输出JSON：{\"panels\": [{\"panel\": 1, \"description\": \"画面\", \"dialog\": \"对白\"}], \"story\": \"剧情概要\"}",
}


@app.get("/health")
async def health():
    return {"name": "sketch-service", "status": "ok", "time": time.time()}


@app.get("/prompts")
async def list_prompts():
    """列出内置提示词模板（前端可选，用户也可自定义）。"""
    return {"templates": PROMPT_TEMPLATES}


@app.post("/recognize")
async def recognize(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    template: str = Form(""),
):
    """图片 + 提示词 → 结构化解读。

    Args:
        file: 图片文件
        prompt: 用户自定义提示词（优先，空则用 template 或默认）
        template: 内置模板名（general/mechanical/sketch_to_3d/...）
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty image")

    # 提示词解析：显式 prompt > 模板 > 默认通用
    effective_prompt = prompt.strip()
    if not effective_prompt and template:
        effective_prompt = PROMPT_TEMPLATES.get(template, "")

    result = recognize_image(content, effective_prompt)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    # 留档
    try:
        UPLOAD_DIR.mkdir(exist_ok=True)
        fname = f"img_{int(time.time())}_{file.filename or 'image.png'}"
        with open(UPLOAD_DIR / fname, "wb") as f:
            f.write(content)
    except Exception:
        pass

    return {"result": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("SKETCH_PORT", "8096")))
