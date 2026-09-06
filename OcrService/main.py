"""OcrService — DesignTool OCR 工具(独立子模块,端口 8099)。

基于 RapidOCR(onnxruntime 本地推理,含中文),免费无需 API key。

POST /ocr   (multipart: file=image.png/jpg) → {"text": "...", "items": [...]}
GET  /health
"""

import os
import time
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI(title="OcrService")

_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


@app.get("/health")
def health():
    return {"name": "ocr-service", "status": "ok", "engine": "rapidocr", "time": time.time()}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """图片 → 文字(本地 OCR,支持中英文)。"""
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty image"}, status_code=400)
    if len(data) > 15 * 1024 * 1024:
        return JSONResponse({"error": "image too large"}, status_code=400)
    ext = os.path.splitext(file.filename or "image.png")[1] or ".png"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(data)
    tmp.close()
    try:
        ocr_engine = _get_ocr()
        result, _elapse = ocr_engine(tmp.name)
        if not result:
            return {"text": "", "items": []}
        items = [{"text": str(box[1][0] if isinstance(box[1], list) else box[1]), "conf": float(box[2]) if len(box) > 2 else 0} for box in result]
        text = "\n".join(it["text"] for it in items)
        return {"text": text, "items": items}
    except Exception as e:
        return JSONResponse({"error": "ocr failed: " + str(e)}, status_code=500)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# MCP 支持:把 OcrService 端点转成 MCP 工具,挂载 /mcp
try:
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))
    from mcp_helper import mount_mcp
    mount_mcp(app, name="OcrService", description="图片/图纸 OCR 文字识别(本地免费)")
except Exception as e:
    print("[mcp] OcrService MCP 挂载跳过:", e)
