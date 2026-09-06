#!/bin/bash
# sketch-service 启动脚本（8096）
# 模型配置：环境变量优先，未设则读 config.json
# 推理/vision 分开配置（与 Anvil 共用命名规范）
# ANVIL_VISION_API_KEY 从 /tmp/vkey.txt 读取（不落明文到脚本）
cd /path/to/DesignTool/SketchService
export ANVIL_VISION_BASE_URL=${ANVIL_VISION_BASE_URL:-https://api.moonshot.cn/v1}
export ANVIL_VISION_MODEL=${ANVIL_VISION_MODEL:-moonshot-v1-128k-vision-preview}
export ANVIL_VISION_API_KEY=${ANVIL_VISION_API_KEY:-$(cat /tmp/vkey.txt 2>/dev/null)}
exec python3 -m uvicorn server:app --host 0.0.0.0 --port 8096
