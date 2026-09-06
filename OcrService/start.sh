#!/bin/bash
# OcrService 启动脚本(端口 8099)
cd "$(dirname "$0")"
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8099
