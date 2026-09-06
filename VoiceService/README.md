# VoiceService — DesignTool 免费语音服务(独立子模块)

> 端口 **8098** · openai-whisper 本地转写 · 免费无 key · 用户未配置语音模型时兜底

## 职责
- **音频 → 文本**:whisper 本地语音转写(中文优先),浏览器/服务端均可调用
- **兜底**:用户在设置页配置了 voice 模型则用其 API;未配置时前端自动走本服务(免费)

## 目录
```
VoiceService/
├── main.py    # FastAPI:POST /recognize(音频→文本), GET /health
└── start.sh   # 启动(8098, whisper tiny)
```

## 启动
```bash
./start.sh          # 或 VOICE_WHISPER_MODEL=small python3 -m uvicorn main:app --port 8098
```
模型:默认 tiny(最快,已缓存 ~75MB);需要更准可换 small/base(首次自动下载)。

## 调用
```
POST /recognize   multipart: file=audio.webm → {"text": "识别文本"}
GET  /health
```

## 部署
- 依赖:openai-whisper + ffmpeg
- 服务:`setsid nohup bash start.sh > /tmp/voice8098.log 2>&1 &`
- nginx 反向代理(可选):`location /voice-api { proxy_pass http://127.0.0.1:8098; }`
- 前端:SketchPad 语音 → 浏览器 Web Speech 优先;失败/不可用 → POST /voice-api/recognize
