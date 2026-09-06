#!/bin/bash
# AdminService 启动脚本(端口 8097)
cd "$(dirname "$0")"
# 加载 .env(JWT secret 等与 Anvil 共享,不加载会用默认 secret 导致两端不一致)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi
# 与 Anvil 共享数据目录(读 downloads.jsonl + 各项目 .design/log)
export ANVIL_DATA_DIR="${ANVIL_DATA_DIR:-$(cd ../Anvil && pwd)/data}"
# JWT secret 与 Anvil 保持一致(已由 .env 加载到环境变量)
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8097
