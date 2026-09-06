"""DraftEngine HTTP 服务(可选):模型 → 图纸。

端口 8100,与 AdminService/VoiceService 同模式。
依赖 ssh 上已装的 fastapi/uvicorn。

接口:
  POST /api/drawing/from-file         multipart 上传模型 → {svg, pdf, fcstd, svg_content, meta}
  POST /api/drawing/from-file/stream  同上,但 SSE 流式返回各阶段进度(load/analyze/view/.../done)
  POST /api/drawing/from-path         {model_path, out_dir, title, project, draft} → 服务端已有模型
  POST /api/drawing/auto              全自动:中间态 → Playwright → VLM 决策标注 → 终稿
  GET  /api/health
  GET  /api/file?path=...             下载产物(SVG/PDF/FCStd,仅限允许目录)

启动: python -m draftengine.api --port 8100
"""

import json
import os
import queue
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import gbstd
from . import kb
from .core import generate_drawing

app = FastAPI(title="DraftEngine", version="0.1.0")


class PathReq(BaseModel):
    model_path: str
    out_dir: str = "/tmp"
    title: str = ""
    project: str = ""
    draft: bool = False


@app.get("/api/health", operation_id="health_check", summary="DraftEngine 健康检查")
def health():
    from .geometry import HAS_FREECAD
    return {"ok": True, "tool": "DraftEngine", "has_freecad": HAS_FREECAD}


@app.get("/api/gbstd", operation_id="get_gb_standards", summary="工程国标知识库(结构化 JSON 全文)")
def get_gbstd():
    """国标知识库全文(结构化 JSON,前端/Agent 可查询)。"""
    return {"sections": {s: gbstd.load(s) for s in gbstd.sections()}}


@app.get("/api/gbstd/md", response_class=PlainTextResponse, operation_id="get_gb_standards_markdown", summary="国标知识库 markdown 导出")
def get_gbstd_md():
    """国标知识库 markdown 导出(喂 RAGFlow 等知识库系统)。"""
    return gbstd.to_markdown()


# === 知识库统一接口(RAG) ===

@app.get("/api/kb/status", operation_id="kb_status", summary="知识库后端健康状态")
def kb_status():
    """知识库后端状态(RAGFlow + 本地)。"""
    return kb.service().status()


@app.get("/api/kb/search", operation_id="kb_search", summary="知识库检索(国标/术语/标准件)")
def kb_search(q: str, top_k: int = 5, backend: str = "auto"):
    """知识库检索:q=查询词,backend=auto/local/ragflow。"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q 不能为空")
    hits = kb.service().search(q, top_k=min(top_k, 20), backend=backend)
    return {"query": q, "backend": backend, "count": len(hits),
            "hits": [h.to_dict() for h in hits]}


@app.get("/api/kb/ask", operation_id="kb_ask", summary="知识库问答(检索增强)")
def kb_ask(q: str, backend: str = "auto"):
    """知识库问答(检索增强;local=规则拼接,ragflow=语义命中片段)。"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q 不能为空")
    return kb.service().ask(q, backend=backend)


@app.post("/api/drawing/from-path", operation_id="generate_drawing_from_path", summary="服务端模型文件生成工程图纸")
def drawing_from_path(req: PathReq):
    if not os.path.exists(req.model_path):
        raise HTTPException(status_code=404, detail="模型文件不存在")
    r = generate_drawing(req.model_path, req.out_dir, title=req.title,
                         project=req.project, draft=req.draft)
    if "error" in r:
        raise HTTPException(status_code=500, detail=r["error"])
    _attach_svg_content(r)
    return r


def _attach_svg_content(r):
    """把 SVG 文件内容附到返回里(前端直接内嵌显示)。"""
    try:
        with open(r["svg"], "r", encoding="utf-8") as f:
            r["svg_content"] = f.read()
    except Exception:
        pass


@app.post("/api/drawing/from-file", operation_id="generate_drawing_from_file", summary="上传 STEP 模型生成工程图纸(三视图+标注)")
async def drawing_from_file(
    file: UploadFile = File(...),
    out_dir: str = "/tmp",
    title: str = "",
    project: str = "",
    draft: bool = False,
):
    """上传模型文件,生成图纸。文件保存到 out_dir。draft=中间态(仅三视图)。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".step", ".stp", ".iges", ".igs", ".brep"):
        raise HTTPException(status_code=400, detail="不支持的格式: %s" % ext)
    os.makedirs(out_dir, exist_ok=True)
    save_path = os.path.join(out_dir, file.filename or ("upload" + ext))
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    r = generate_drawing(save_path, out_dir, title=title or Path(save_path).stem,
                         project=project, draft=draft)
    if "error" in r:
        raise HTTPException(status_code=500, detail=r["error"])
    # 附上 SVG 内容(前端直接内嵌显示,无需再取文件)
    _attach_svg_content(r)
    return r


def _sse(obj) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@app.post("/api/drawing/from-file/stream", operation_id="generate_drawing_stream", summary="上传模型 SSE 流式生成工程图纸")
async def drawing_from_file_stream(
    file: UploadFile = File(...),
    out_dir: str = "/tmp",
    title: str = "",
    project: str = "",
    draft: bool = False,
):
    """上传模型文件,SSE 流式返回生成进度:
    data: {"type":"stage","stage":"load|analyze|view|annotate|export","msg":...}
    ...
    data: {"type":"done","result":{svg,pdf,fcstd,svg_content,meta,...}}
    data: {"type":"error","content":"..."}  (失败时)
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".step", ".stp", ".iges", ".igs", ".brep"):
        raise HTTPException(status_code=400, detail="不支持的格式: %s" % ext)
    os.makedirs(out_dir, exist_ok=True)
    save_path = os.path.join(out_dir, file.filename or ("upload" + ext))
    with open(save_path, "wb") as f:
        f.write(await file.read())

    def event_stream():
        yield _sse({"type": "stage", "stage": "upload",
                    "msg": "文件已上传: %s (%.1f KB)"
                           % (os.path.basename(save_path),
                              os.path.getsize(save_path) / 1024.0)})
        q: "queue.Queue" = queue.Queue()

        def on_event(e):
            q.put(("event", e))

        def work():
            try:
                r = generate_drawing(save_path, out_dir,
                                     title=title or Path(save_path).stem,
                                     project=project, draft=draft,
                                     on_event=on_event)
                q.put(("result", r))
            except Exception as ex:  # 兜底:core 未捕获的异常也走 SSE
                q.put(("error", str(ex)))
            finally:
                q.put(None)

        threading.Thread(target=work, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            kind, payload = item
            if kind == "event":
                yield _sse(payload)
            elif kind == "result":
                if "error" in payload:
                    yield _sse({"type": "error", "content": payload["error"]})
                else:
                    _attach_svg_content(payload)
                    yield _sse({"type": "done", "result": payload})
            else:
                yield _sse({"type": "error", "content": payload})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/file", operation_id="download_artifact", summary="下载图纸产物(SVG/PDF/FCStd)")
def get_file(path: str):
    """下载产物文件。仅允许 DRAFTENGINE_OUT_ROOT(默认 /tmp)下的路径。"""
    root = os.path.realpath(os.environ.get("DRAFTENGINE_OUT_ROOT", "/tmp"))
    p = os.path.realpath(path)
    if not (p == root or p.startswith(root + os.sep)):
        raise HTTPException(status_code=403, detail="路径不在允许的目录内")
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(p, filename=os.path.basename(p))


class AutoReq(BaseModel):
    """全自动管线:模型 → 中间态(三视图) → VLM 决策标注 → 终稿。"""
    model_path: str
    out_dir: str = "/tmp"
    title: str = ""
    project: str = ""


@app.post("/api/drawing/auto", operation_id="generate_drawing_auto", summary="全自动管线:三视图→VLM 标注决策→终稿")
def drawing_auto(req: AutoReq):
    """四步管线:
    ① bbox/特征分析(方位) ② HLR 三视图中间态(无标注/标题栏)
    ③ Playwright 渲染 PNG ④ VLM 决策标注 → 终稿(加标题栏+PDF/FCStd)
    """
    from . import generate_drawing
    from .validate import render_png
    from . import vlm

    if not os.path.exists(req.model_path):
        raise HTTPException(status_code=404, detail="模型文件不存在")
    # 中间态(另存,避免被终稿同名覆盖)
    d = generate_drawing(req.model_path, req.out_dir, title=req.title,
                         project=req.project, draft=True)
    if "error" in d:
        raise HTTPException(status_code=500, detail=d["error"])
    draft_svg = os.path.splitext(d["svg"])[0] + "_draft.svg"
    os.replace(d["svg"], draft_svg)
    d["svg"] = draft_svg
    png = render_png(draft_svg)
    annotations = []
    vlm_info = {"png": png}
    if png:
        v = vlm.suggest_annotations(png, d["meta"])
        if "annotations" in v:
            annotations = v["annotations"]
            vlm_info["decision"] = annotations
        else:
            vlm_info["error"] = v.get("error")
    else:
        vlm_info["error"] = "Playwright 渲染失败(跳过 VLM,用默认标注)"
    # 终稿(VLM 意图或默认规则)
    r = generate_drawing(req.model_path, req.out_dir, title=req.title,
                         project=req.project, annotations=annotations)
    if "error" in r:
        raise HTTPException(status_code=500, detail=r["error"])
    r["draft_svg"] = d["svg"]
    r["draft_png"] = png
    r["vlm"] = vlm_info
    _attach_svg_content(r)
    return r


def main():
    import uvicorn
    # MCP 支持:把 DraftEngine 端点转成 MCP 工具,挂载 /mcp
    try:
        try:
            from .mcp_helper import mount_mcp  # 优先包内
        except ImportError:
            import sys as _sys
            _root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            if _root not in _sys.path:
                _sys.path.insert(0, _root)
            from mcp_helper import mount_mcp  # 退回 DesignTool 目录
        mount_mcp(app, name="DraftEngine",
                  description="3D 模型(STEP)→ 工程图纸(第一角三视图+尺寸标注,输出 SVG/PDF/FCStd)")
    except Exception as e:
        print("[mcp] DraftEngine MCP 挂载跳过:", e)
    port = int(os.environ.get("DRAFTENGINE_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
