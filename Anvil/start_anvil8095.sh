#!/bin/bash
# Anvil 生产启动脚本(ssh remote-server)
cd /mnt/data/develop/elderly-care-robot/DesignTool/Anvil
export ANVIL_ENV=production
# 数据目录与源码分离:运行时数据(projects/output/anvil.db/日志)全在 data/
export ANVIL_DATA_DIR="${ANVIL_DATA_DIR:-$PWD/data}"
# 加载 .env(LLM key 等,仅本地,不提交 git)
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
# 会话连续性要求单 worker:agents 缓存是进程内 dict,多 worker 各自持有
# 独立缓存 → 同一项目两次请求落在不同 worker 会重建 agent、丢失上轮模型状态。
# --reload:代码改动自动重载(开发调试用);reload 模式下 worker 数强制为 1。
exec python3 -m uvicorn anvil.web:app --host 0.0.0.0 --port 8095 --workers 1 --reload
