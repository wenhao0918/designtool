"""VoiceService — DesignTool 免费语音服务(独立子模块,端口 8098)。

基于 openai-whisper 本地转写,免费、无需 API key。
用户未配置语音模型(voice model_configs)时,前端用它兜底。

POST /recognize  (multipart: file=audio.wav/webm/mp3) → {"text": "..."}
GET  /health
"""

import os
import time
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI(title="VoiceService")

# 模型名可配置,默认 tiny(最快,已缓存)
WHISPER_MODEL = os.environ.get("VOICE_WHISPER_MODEL", "tiny")
_model = None


def _get_model():
    global _model
    if _model is None:
        import whisper
        _model = whisper.load_model(WHISPER_MODEL)
    return _model


@app.get("/health")
def health():
    return {"name": "voice-service", "status": "ok", "model": WHISPER_MODEL, "time": time.time()}


@app.post("/recognize")
async def recognize(file: UploadFile = File(...)):
    """音频文件 → 文本(whisper 本地转写)。"""
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty audio"}, status_code=400)
    if len(data) > 25 * 1024 * 1024:
        return JSONResponse({"error": "audio too large"}, status_code=400)

    ext = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(data)
    tmp.close()
    try:
        model = _get_model()
        result = model.transcribe(tmp.name, language="zh", fp16=False)
        text = (result.get("text") or "").strip()
        return {"text": text}
    except Exception as e:
        return JSONResponse({"error": "transcribe failed: " + str(e)}, status_code=500)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# MCP 支持:把 VoiceService 端点转成 MCP 工具,挂载 /mcp
try:
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))
    from mcp_helper import mount_mcp
    mount_mcp(app, name="VoiceService", description="语音识别(whisper 本地转写)")
except Exception as e:
    print("[mcp] VoiceService MCP 挂载跳过:", e)
