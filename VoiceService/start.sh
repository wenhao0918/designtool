#!/bin/bash
# VoiceService 启动脚本(端口 8098)
cd "$(dirname "$0")"
export VOICE_WHISPER_MODEL="${VOICE_WHISPER_MODEL:-tiny}"
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8098
